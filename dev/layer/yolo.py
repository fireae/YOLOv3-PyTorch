# Copyright 2020 Lorna Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
import torch
import torch.nn as nn


class YOLO(nn.Module):
    def __init__(self, anchors, num_classes, stride):
        super(YOLO, self).__init__()

        self.anchors = torch.Tensor(anchors)
        self.num_anchors = len(anchors)  # number of anchors (3)
        self.num_classes = num_classes  # number of classes (80)
        self.stride = stride  # number of stride ()
        self.num_outputs = num_classes + 5  # number of outputs (85)

    def forward(self, p):
        batch_size, _, ny, nx = p.shape  # bs, 255, 13, 13

        p = p.view(batch_size, self.num_anchors, 5 + self.num_classes, ny,
                   nx).permute(0, 3, 4, 1, 2)

        p_de = self.decode(p.clone())

        return p, p_de

    def decode(self, p):
        batch_size, output_size = p.shape[:2]

        device = p.device
        stride = self.stride
        anchors = (1.0 * self.num_anchors).to(device)

        conv_raw_dxdy = p[:, :, :, :, 0:2]
        conv_raw_dwdh = p[:, :, :, :, 2:4]
        conv_raw_conf = p[:, :, :, :, 4:5]
        conv_raw_prob = p[:, :, :, :, 5:]

        y = torch.arange(0, output_size).unsqueeze(1).repeat(1, output_size)
        x = torch.arange(0, output_size).unsqueeze(0).repeat(output_size, 1)
        grid_xy = torch.stack([x, y], dim=-1)
        grid_xy = grid_xy.unsqueeze(0).unsqueeze(3).repeat(
            batch_size, 1, 1, 3, 1).float().to(device)

        pred_xy = (torch.sigmoid(conv_raw_dxdy) + grid_xy) * stride
        pred_wh = (torch.exp(conv_raw_dwdh) * anchors) * stride
        pred_xywh = torch.cat([pred_xy, pred_wh], dim=-1)
        pred_conf = torch.sigmoid(conv_raw_conf)
        pred_prob = torch.sigmoid(conv_raw_prob)
        pred_bbox = torch.cat([pred_xywh, pred_conf, pred_prob], dim=-1)

        if self.training:
            return pred_bbox
        else:
            return pred_bbox.view(-1, 5 + self.num_classes)


def create_grids(self, image_size=416, ng=(13, 13), device="cpu",
                 dtype=torch.float32):
    nx, ny = ng  # x and y grid size
    self.img_size = max(image_size)
    self.stride = self.img_size / max(ng)

    # build xy offsets
    yv, xv = torch.meshgrid([torch.arange(ny), torch.arange(nx)])
    self.grid_xy = torch.stack((xv, yv), 2).to(device).type(dtype).view(
        (1, 1, ny, nx, 2))

    # build wh gains
    self.anchor_vec = self.anchors.to(device) / self.stride
    self.anchor_wh = self.anchor_vec.view(1, self.na, 1, 1, 2).type(dtype)
    self.ng = torch.Tensor(ng).to(device)
    self.nx = nx
    self.ny = ny


class YOLOLayer(nn.Module):
    def __init__(self, anchors, nc, yolo_index, layers):
        super(YOLOLayer, self).__init__()
        self.anchors = torch.Tensor(anchors)
        self.index = yolo_index  # index of this layer in layers
        self.layers = layers  # model output layer indices
        self.nl = len(layers)  # number of output layers (3)
        self.na = len(anchors)  # number of anchors (3)
        self.nc = nc  # number of classes (80)
        self.no = nc + 5  # number of outputs (85)
        self.nx = 0  # initialize number of x grid points
        self.ny = 0  # initialize number of y grid points

    def forward(self, pred, image_size, out):
        batch_size, _, ny, nx = pred.shape  # batch_size, 255, 13, 13
        if (self.nx, self.ny) != (nx, ny):
            create_grids(self, image_size, (nx, ny), pred.device, pred.dtype)

        # p.view(batch_size, 255, 13, 13) -- > (batch_size, 3, 13, 13, 85)
        # (batch_size, anchors, grid, grid, classes + xywh)
        # prediction
        pred = pred.view(batch_size, self.na, self.no, self.ny,
                         self.nx).permute(0, 1, 3, 4, 2).contiguous()

        if self.training:
            return pred

        else:  # inference
            io = pred.clone()  # inference output
            io[..., :2] = torch.sigmoid(io[..., :2]) + self.grid_xy  # xy
            # wh yolo method
            io[..., 2:4] = torch.exp(io[..., 2:4]) * self.anchor_wh
            io[..., :4] *= self.stride
            torch.sigmoid_(io[..., 4:])
            # view [1, 3, 13, 13, 85] as [1, 507, 85]
            return io.view(batch_size, -1, self.no), pred
