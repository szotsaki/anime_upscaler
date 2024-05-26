import frame_esrgan
import cv2
from tqdm import tqdm
import os
import argparse
import shutil
import image_slicer
from image_slicer import join
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import subprocess
import ffmpegcv


parser = argparse.ArgumentParser()
parser.add_argument('-m', '--model_path', type=str, help='REQUIRED: specify path of the model being used')
parser.add_argument('-i', '--input', type=str, help='REQUIRED: specify path of the image you want to upscale')
parser.add_argument('-o', '--output', type=str, help='REQUIRED: specify path where you want to save image')
parser.add_argument('-S', '--save-prefix', type=str, help='OPTIONAL: Save frames with prefix to save memory')
parser.add_argument('-s', '--slice', nargs='?', type=int, const=4, help='OPTIONAL: specify weather to split frames, recommended to use to help with VRAM unless you got a fucken quadro or something' )
parser.add_argument('-a', '--audio', action='store_true', help='OPTIONAL: specify weather you want to copy audio from source as well')
parser.add_argument('-c', '--clear_temp', action='store_true', help='OPTIONAL: specify weather you want to clear temporary folder with upscaled frames after you are finished with final video')
parser.add_argument('--cuda-encode', action='store_true', help='OPTIONAL: use CUDA to combine frames')
args = parser.parse_args()

def extract_frameno(fname):
    no_ext = fname.rsplit('.', 1)[0]
    only_num = no_ext.rsplit('_', 1)[1]

    return int(only_num)

def extract_frames(vid_path, save_prefix=''):
    save = '{}_{{}}.png'.format(save_prefix) if save_prefix else False

    if not os.path.exists(vid_path):
        raise RuntimeError(f'path missing {vid_path}')

    folder_name = vid_path.split('/')[-1].split('.')[0]
    original = os.path.join('tmp', folder_name, 'original')

    # Reuse frames if we have them
    if save_prefix:
        files = os.listdir(original)
        files = (f for f in files if f.startswith(save_prefix) and '_' in f and f.endswith('.png'))
        files = sorted(files, key=extract_frameno)
        if files:
            print(f'Found {len(files)} frames extracted')
            return files

    vid = cv2.VideoCapture(vid_path)
    images = []
    count = 0

    success, image = vid.read()
    while success:
        if not save:
            images.append(image)
        else:
            if count % 1000 == 0:
                print('saving frame {}...'.format(count))
            fname = save.format(count)
            fpath = os.path.join(original, fname)
            cv2.imwrite(fpath, image)
            images.append(fname)
        success, image = vid.read()
        count += 1
    return images

def get_fps(vid_path):
    vid = cv2.VideoCapture(vid_path)
    return vid.get(cv2.CAP_PROP_FPS)

def create_temp_folder(vid_path):
    if os.path.exists('tmp'):
        folder_name = vid_path.split('/')[-1].split('.')[0]
        tmp_path = os.path.join('tmp', folder_name)
        if not os.path.exists(tmp_path):
            os.mkdir(tmp_path)
    else:
        os.mkdir('tmp')
        create_temp_folder(vid_path)

def get_dir(path):
    if not os.path.exists(path):
        os.mkdir(path)
    return path

def setup_frames(vid_path, save_prefix=''):
    create_temp_folder(vid_path)

    folder_name = vid_path.split('/')[-1].split('.')[0]

    original = os.path.join('tmp', folder_name, 'original')
    upscaled = os.path.join('tmp', folder_name, 'upscaled')

    if not os.path.exists(original):
        os.mkdir(original)
    if not os.path.exists(upscaled):
        os.mkdir(upscaled)

    images = extract_frames(vid_path, save_prefix=save_prefix)
    if not save_prefix:
        for i in tqdm(range(len(images))):
            fname = 'frame_{}.png'.format(i)
            ipath = os.path.join(original, fname)
            cv2.imwrite(ipath, images[i])

def upscale(vid_path, slice=None, save_prefix=''):
    folder_name = vid_path.split('/')[-1].split('.')[0]

    original = os.path.join('tmp', folder_name, 'original')
    upscaled = os.path.join('tmp', folder_name, 'upscaled')

    print('extracting frames...')
    setup_frames(vid_path, save_prefix=save_prefix)

    print('upscaling...')
    for i in tqdm(os.listdir(original)):
        original_f = os.path.join(original, i)
        upscaled_f = os.path.join(upscaled, i)

        # Reuse what we have if possible
        if not os.path.exists(upscaled_f):
            if slice:
                out = frame_esrgan.upscale_slice(args.model_path, original_f, slice)
            else:
                out = frame_esrgan.upscale(args.model_path, original_f)
            cv2.imwrite(upscaled_f, out)

def combine_frames(video_path, new_video_path, save_prefix='', cuda_encode=False):
    folder_name = video_path.split('/')[-1].split('.')[0]
    upscaled = os.path.join('tmp', folder_name, 'upscaled')

    if not save_prefix:
        save_prefix = 'frame'

    images = [img for img in os.listdir(upscaled)]
    fps = get_fps(video_path)

    print(f'combining {len(images)} frames into "{new_video_path}" ...')
    video_writer = ffmpegcv.VideoWriterNV if cuda_encode else ffmpegcv.VideoWriter
    with video_writer(new_video_path, codec='hevc', fps=fps) as video:
        for i in tqdm(range(len(images))):
            fname = f'{save_prefix}_{i}.png'
            fpath = os.path.join(upscaled, fname)
            video.write(cv2.imread(fpath))

    cv2.destroyAllWindows()

def copy_audio(original_video_path, new_video_path, new_name=''):
    #ffmpeg -i input_0.mp4 -i input_1.mp4 -c copy -map 0:v:0 -map 1:a:0 -shortest out.mp4
    tmp_name = new_video_path.split('.')[0] + '_tmp.' + new_video_path.split('.')[-1]
    subprocess.run([
        'ffmpeg',
        '-i',
        new_video_path,
        '-i',
        original_video_path,
        '-c',
        'copy',
        '-map',
        '0:v:0',
        '-map',
        '1:a:0',
        '-shortest',
        tmp_name
    ])

    os.replace(tmp_name, new_video_path)


if __name__ == '__main__':
    if args.model_path and args.input and args.output:
        try:
            upscale(args.input, slice=args.slice, save_prefix=args.save_prefix)
            combine_frames(args.input, args.output, args.save_prefix, args.cuda_encode)
            if args.audio:
                copy_audio(args.input, args.output)
            if args.clear_temp:
                shutil.rmtree('tmp')
        except Exception as e:
            print(e)
            shutil.rmtree('tmp')
            print('Remove tmp if you want to start from scratch')
            raise
