import cv2
import os
import glob

# Set the path to the LettuceMOTS image sequence folder
image_folder = r'D:\download\LettuceMOTS\test\images\0007'
video_name = 'output_video.mp4'

# Fetch all PNG images and sort them to maintain sequential order
images = sorted(glob.glob(os.path.join(image_folder, '*.png')))

if not images:
    print("No images found. Please check the path!")
    exit()

# Read the first frame to get the correct height and width for the video
first_frame = cv2.imread(images[0])
height, width, layers = first_frame.shape

# Define the codec and create a VideoWriter object (mp4v is standard for .mp4)
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
fps = 10  # Adjust frames per second based on the dataset's capture rate

video = cv2.VideoWriter(video_name, fourcc, fps, (width, height))

print("Compiling video...")
for image_path in images:
    frame = cv2.imread(image_path)
    
    # Optional: You can parse the LettuceMOTS label files (.txt) here 
    # and use cv2.rectangle() to draw tracking boxes before writing the frame!
    
    video.write(frame)

video.release()
print(f"Success! Video saved as {video_name}")