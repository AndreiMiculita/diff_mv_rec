"""
Finding highest entropy locally
"""
import os
import argparse
import glob

import torch
import torch.nn as nn
import numpy as np
from skimage.io import imread, imsave
import tqdm
import imageio
from torch.special import entr


import neural_renderer as nr

current_dir = os.path.dirname(os.path.realpath(__file__))
data_dir = os.path.join(current_dir, 'data')

# TODO: https://discuss.pytorch.org/t/calculating-the-entropy-loss/14510/3
# see also
# * https://github.com/pytorch/pytorch/issues/9993
# * https://pytorch.org/docs/master/special.html

def entropy_loss(residual):
    # src https://github.com/pytorch/pytorch/issues/15829#issuecomment-843182236
    # residual.shape[0] -> batch size
    # residual.shape[1] -> Number of channels
    # residual.shape[2] -> Width
    # residual.shape[3] -> Height
    print(residual.shape)
    entropy = torch.zeros(residual.shape[0], 1, requires_grad=True).cuda()
    image_size = float(residual.shape[1] * residual.shape[2] * residual.shape[3])
    for i in range(0, residual.shape[0]):  # loop over batch
        _, counts = torch.unique(residual[i].data.flatten(start_dim=0), dim=0,
                                 return_counts=True)  # flatt tensor and compute the unique values
        p = counts / image_size  # compute the
        entropy[i] = torch.sum(p * torch.log2(p)) * -1
    return entropy.mean()


def other_entropy(input_tensor):
    # src: https://github.com/pytorch/pytorch/issues/15829#issuecomment-725347711
    lsm = nn.LogSoftmax()
    log_probs = lsm(input_tensor)
    probs = torch.exp(log_probs)
    p_log_p = log_probs * probs
    entropy = -p_log_p.mean()
    return entropy


def entropy(p, dim = -1, keepdim=None):
    # src: https://github.com/pytorch/pytorch/issues/9993
    return -torch.where(p > 0, p * p.log(), p.new([0.0])).sum(dim=dim, keepdim=keepdim)  # can be a scalar, when PyTorch.supports it



class Model(nn.Module):
    def __init__(self, filename_obj, filename_ref=None):
        super(Model, self).__init__()
        # load .obj
        vertices, faces = nr.load_obj(filename_obj)
        self.register_buffer('vertices', vertices[None, :, :])
        self.register_buffer('faces', faces[None, :, :])

        # create textures
        texture_size = 2
        textures = torch.ones(1, self.faces.shape[1], texture_size, texture_size, texture_size, 3, dtype=torch.float32)
        self.register_buffer('textures', textures)

        # load reference image
        image_ref = torch.from_numpy((imread(filename_ref).max(-1) != 0).astype(np.float32))
        self.register_buffer('image_ref', image_ref)

        # camera parameters
        self.camera_position = nn.Parameter(torch.from_numpy(np.array([6, 10, -14], dtype=np.float32)))

        # setup renderer
        renderer = nr.Renderer(camera_mode='look_at')
        renderer.eye = self.camera_position
        self.renderer = renderer

    def forward(self):
        image = self.renderer(self.vertices, self.faces, mode='silhouettes')
        entropy = entr(image).mean() * 10.0
        loss = 1.0 / entropy
        print(f"shape {loss.shape} {entropy}")
        print(f"loss {loss}")
        return loss


def make_gif(filename):
    with imageio.get_writer(filename, mode='I') as writer:
        for filename in sorted(glob.glob('/tmp/_tmp_*.png')):
            writer.append_data(imread(filename))
            os.remove(filename)
    writer.close()


def make_reference_image(filename_ref, filename_obj):
    model = Model(filename_obj)
    model.cuda()

    model.renderer.eye = nr.get_points_from_angles(2.732, 30, -15)
    images, _, _ = model.renderer.render(model.vertices, model.faces, torch.tanh(model.textures))
    image = images.detach().cpu().numpy()[0]
    imsave(filename_ref, image)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-io', '--filename_obj', type=str, default=os.path.join(data_dir, 'teapot.obj'))
    parser.add_argument('-ir', '--filename_ref', type=str, default=os.path.join(data_dir, 'example4_ref.png'))
    parser.add_argument('-or', '--filename_output', type=str, default=os.path.join(data_dir, 'example4_result.gif'))
    parser.add_argument('-mr', '--make_reference_image', type=int, default=0)
    parser.add_argument('-g', '--gpu', type=int, default=0)
    args = parser.parse_args()

    if args.make_reference_image:
        make_reference_image(args.filename_ref, args.filename_obj)

    model = Model(args.filename_obj, args.filename_ref)
    model.cuda()

    # optimizer = chainer.optimizers.Adam(alpha=0.1)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.1)
    loop = tqdm.tqdm(range(1000))
    for i in loop:
        optimizer.zero_grad()
        loss = model()
        loss.backward()
        optimizer.step()
        images, _, _ = model.renderer(model.vertices, model.faces, torch.tanh(model.textures))
        image = images.detach().cpu().numpy()[0].transpose(1,2,0)
        imsave('/tmp/_tmp_%04d.png' % i, image)
        loop.set_description('Optimizing (loss %.4f)' % loss.data)
        if loss.item() < 70:
            break
    make_gif(args.filename_output)


if __name__ == '__main__':
    main()