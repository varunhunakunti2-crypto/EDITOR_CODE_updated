# Save this as image_editor_local.py
import torch
from diffusers import StableDiffusionInstructPix2PixPipeline
from PIL import Image
import os

def main():
    # Initialize editor
    print("🚀 Starting Local Image Editor...")
    editor = LocalImageEditor()
    
    # Your inputs
    input_image = "sample.jpg"  # Change to your image path
    user_prompt = "add a bright sun in the background"  # Change to your prompt
    output_image = "edited_image.jpg"
    
    # Edit the image
    success = editor.edit_image(input_image, user_prompt, output_image)
    
    if success:
        print("🎉 Image editing completed successfully!")
    else:
        print("❌ Image editing failed")

if __name__ == "__main__":
    main()
