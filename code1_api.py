# Install: pip install replicate requests Pillow
import replicate
import requests
import os
from PIL import Image

class ReplicateImageEditor:
    def __init__(self, api_token):
        """
        Initialize with Replicate API token
        Get token from: https://replicate.com/account
        """
        self.api_token = api_token
        os.environ["REPLICATE_API_TOKEN"] = api_token
        print("âœ… Replicate editor initialized")
    
    def edit_image(self, input_image_path, prompt, output_image_path):
        """
        Edit image using Replicate API
        
        Args:
            input_image_path: Path to input image
            prompt: Text instruction for editing
            output_image_path: Path to save edited image
        """
        try:
            # Check if input file exists
            if not os.path.exists(input_image_path):
                print(f"âŒ Input image not found: {input_image_path}")
                return False
            
            print(f"ðŸ“¸ Processing: {input_image_path}")
            print(f"ðŸŽ¨ Prompt: '{prompt}'")
            
            # Call Replicate API
            output = replicate.run(
                "timbrooks/instruct-pix2pix:30c1d0b916a6f8efce20493f5d61ee27491ab2a60437c13c588468b9810ec23f",
                input={
                    "image": open(input_image_path, "rb"),
                    "prompt": prompt,
                    "num_outputs": 1,
                    "num_inference_steps": 20,
                    "image_guidance_scale": 1.5,
                    "guidance_scale": 7.0
                }
            )
            
            # Download the result
            if output:
                image_url = output[0]
                print(f"ðŸ“¥ Downloading result from: {image_url}")
                
                response = requests.get(image_url)
                if response.status_code == 200:
                    with open(output_image_path, 'wb') as f:
                        f.write(response.content)
                    
                    # Verify the image
                    img = Image.open(output_image_path)
                    print(f"âœ… Success! Edited image saved: {output_image_path} ({img.size[0]}x{img.size[1]})")
                    return True
                else:
                    print(f"âŒ Download failed: {response.status_code}")
                    return False
            else:
                print("âŒ No output from API")
                return False
                
        except Exception as e:
            print(f"âŒ API call failed: {e}")
            return False

# USAGE EXAMPLE
if __name__ == "__main__":
    # Initialize with your Replicate token
    # Get token from: https://replicate.com/account
    token = os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        raise SystemExit("Set REPLICATE_API_TOKEN in your environment before running this example.")
    editor = ReplicateImageEditor(token)
    
    # Edit your image
    editor.edit_image(
        input_image_path="sample.jpg",           # Your input image
        prompt="add a bright sun in the background",  # Your editing instruction
        output_image_path="api_output.jpg"       # Output file
    )
