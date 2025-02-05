import os
import sys
import time
import colorsys
import argparse
import os.path as osp
from glob import glob
from collections import defaultdict

import cv2
import torch
import joblib
import imageio
import numpy as np
from smplx import SMPL
from loguru import logger

from configs.config import get_cfg_defaults
from lib.data.datasets import CustomDataset
from lib.models import build_network, build_body_model
from lib.models.preproc.detector import DetectionModel
from lib.models.preproc.extractor import FeatureExtractor
from lib.utils.transforms import matrix_to_axis_angle
from lib.utils.imutils import avg_preds


try: 
    from lib.models.preproc.slam import SLAMModel
    _run_global = True
except: 
    logger.info('DPVO is not properly installed. Only estimate in local coordinates !')
    _run_global = False

def prepare_cfg():
    cfg = get_cfg_defaults()
    cfg.merge_from_file('configs/yamls/demo.yaml')
    return cfg

def load_video(video):
    cap = cv2.VideoCapture(video)
    assert cap.isOpened(), f'Faild to load video file {video}'
    fps = cap.get(cv2.CAP_PROP_FPS)
    length = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width, height = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)

    return cap, fps, length, width, height


class WHAM_API(object):
    def __init__(self):
        self.cfg = prepare_cfg()
        self.network = build_network(self.cfg, build_body_model(self.cfg.DEVICE, self.cfg.TRAIN.BATCH_SIZE * self.cfg.DATASET.SEQLEN))
        self.network.eval()
        self.detector = DetectionModel(self.cfg.DEVICE.lower())
        self.extractor = FeatureExtractor(self.cfg.DEVICE.lower())
        self.slam = None
    
    @torch.no_grad()
    def preprocessing(self, video, cap, fps, length, output_dir):
        if not (osp.exists(osp.join(output_dir, 'tracking_results.pth')) and 
                osp.exists(osp.join(output_dir, 'slam_results.pth'))):
            while (cap.isOpened()):
                flag, img = cap.read()
                if not flag: break
                
                # 2D detection and tracking
                self.detector.track(img, fps, length)
                
                # SLAM
                if self.slam is not None: 
                    self.slam.track()

            tracking_results = self.detector.process(fps)
            
            if self.slam is not None: 
                slam_results = self.slam.process()
            else:
                slam_results = np.zeros((length, 7))
                slam_results[:, 3] = 1.0    # Unit quaternion
        
            # Extract image features
            # TODO: Merge this into the previous while loop with an online bbox smoothing.
            tracking_results = self.extractor.run(video, tracking_results)
            # Save the processed data
            joblib.dump(tracking_results, osp.join(output_dir, 'tracking_results.pth'))
            joblib.dump(slam_results, osp.join(output_dir, 'slam_results.pth'))
        
        # If the processed data already exists, load the processed data
        else:
            tracking_results = joblib.load(osp.join(output_dir, 'tracking_results.pth'))
            slam_results = joblib.load(osp.join(output_dir, 'slam_results.pth'))

        return tracking_results, slam_results
    
    @torch.no_grad()
    def wham_inference(self, tracking_results, slam_results, width, height, fps, output_dir):
        # Build dataset
        dataset = CustomDataset(self.cfg, tracking_results, slam_results, width, height, fps)
        
        # run WHAM
        results = defaultdict(dict)

        n_subjs = len(dataset)

        for subj in range(n_subjs):
            with torch.no_grad():
                if self.cfg.FLIP_EVAL:
                    continue
                    # Forward pass with flipped input
                    # flipped_batch = dataset.load_data(subj, True)
                    # _id, x, inits, features, mask, init_root, cam_angvel, frame_id, kwargs = flipped_batch
                    # flipped_pred = self.network(x, inits, features, mask=mask, init_root=init_root, cam_angvel=cam_angvel, return_y_up=True, **kwargs)
                    
                    # # Forward pass with normal input
                    # batch = dataset.load_data(subj)
                    # _id, x, inits, features, mask, init_root, cam_angvel, frame_id, kwargs = batch
                    # pred = self.network(x, inits, features, mask=mask, init_root=init_root, cam_angvel=cam_angvel, return_y_up=True, **kwargs)
                    
                    # # Merge two predictions
                    # flipped_pose, flipped_shape = flipped_pred['pose'].squeeze(0), flipped_pred['betas'].squeeze(0)
                    # pose, shape = pred['pose'].squeeze(0), pred['betas'].squeeze(0)
                    # flipped_pose, pose = flipped_pose.reshape(-1, 24, 6), pose.reshape(-1, 24, 6)
                    # avg_pose, avg_shape = avg_preds(pose, shape, flipped_pose, flipped_shape)
                    # avg_pose = avg_pose.reshape(-1, 144)
                    # avg_contact = (flipped_pred['contact'][..., [2, 3, 0, 1]] + pred['contact']) / 2
                    
                    # # Refine trajectory with merged prediction
                    # self.network.pred_pose = avg_pose.view_as(self.network.pred_pose)
                    # self.network.pred_shape = avg_shape.view_as(self.network.pred_shape)
                    # self.network.pred_contact = avg_contact.view_as(self.network.pred_contact)
                    # output = self.network.forward_smpl(**kwargs)
                    # pred = self.network.refine_trajectory(output, cam_angvel, return_y_up=True)
                
                else:
                    # data
                    batch = dataset.load_data(subj)
                    _id, x, inits, features, mask, init_root, cam_angvel, frame_id, kwargs = batch
                    
                    # inference
                    pred = self.network(x, inits, features, mask=mask, init_root=init_root, cam_angvel=cam_angvel, return_y_up=True, **kwargs)
            
            
            # ========= Store results ========= #
            pred_body_pose = matrix_to_axis_angle(pred['poses_body']).cpu().numpy().reshape(-1, 69)
            pred_root = matrix_to_axis_angle(pred['poses_root_cam']).cpu().numpy().reshape(-1, 3)
            pred_root_world = matrix_to_axis_angle(pred['poses_root_world']).cpu().numpy().reshape(-1, 3)
            pred_pose = np.concatenate((pred_root, pred_body_pose), axis=-1)
            pred_pose_world = np.concatenate((pred_root_world, pred_body_pose), axis=-1)
            pred_trans = (pred['trans_cam'] - self.network.output.offset).cpu().numpy()
            
            results[_id]['pose'] = pred_pose
            results[_id]['trans'] = pred_trans
            results[_id]['pose_world'] = pred_pose_world
            results[_id]['trans_world'] = pred['trans_world'].cpu().squeeze(0).numpy()
            results[_id]['betas'] = pred['betas'].cpu().squeeze(0).numpy()
            results[_id]['verts'] = (pred['verts_cam'] + pred['trans_cam'].unsqueeze(1)).cpu().numpy()
            results[_id]['frame_ids'] = frame_id
        
        joblib.dump(slam_results, osp.join(output_dir, 'wham_results.pth'))
        return results
    
    @torch.no_grad()
    def __call__(self, video, output_dir='output/demo', calib=None, run_global=True, visualize=True):
        # load video information
        cap, fps, length, width, height = load_video(video)
        os.makedirs(output_dir, exist_ok=True)

        # Whether or not estimating motion in global coordinates
        run_global = run_global and _run_global
        if run_global: self.slam = SLAMModel(video, output_dir, width, height, calib)
        
        # preprocessing to get detection, tracking, slam results and image features from video input
        tracking_results, slam_results = self.preprocessing(video, cap, fps, length, output_dir)

        # WHAM forward inference to get the results
        results = self.wham_inference(tracking_results, slam_results, width, height, fps, output_dir)
        
        # Visualize
        if visualize:
            from lib.vis.run_vis import run_vis_on_demo
            run_vis_on_demo(self.cfg, video, results, output_dir, self.network.smpl, vis_global=run_global)
        
        return results, tracking_results, slam_results


if __name__ == '__main__':
    #from wham_api import WHAM_API
    wham_model = WHAM_API()
    input_video_path = 'examples/IMG_9732.mov'
    results, tracking_results, slam_results = wham_model(input_video_path)