# ---------- INSTALL REQUIRED LIBRARIES ----------
# pip install diffusers transformers accelerate torch torchvision safetensors pillow

import torch
from diffusers import StableDiffusionInpaintPipeline
from PIL import Image, ImageDraw

# ---------- LOAD THE MODEL ----------
model_id = "stabilityai/stable-diffusion-2-inpainting"

pipe = StableDiffusionInpaintPipeline.from_pretrained(
    model_id,
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
)
pipe = pipe.to("cuda" if torch.cuda.is_available() else "cpu")

# ---------- USER INPUTS ----------
image_path = "test.jpg"   # Input image
prompt = "add a television on the wall"   # Your prompt
mask_path = "mask.png"    # Save / reuse mask

# ---------- LOAD INPUT IMAGE ----------
init_image = Image.open(image_path).convert("RGB").resize((512, 512))

# ---------- OPTION 1: AUTO-GENERATE A SIMPLE RECTANGULAR MASK ----------
# Example: create a white rectangle where TV should go (rest = black)
mask_image = Image.new("RGB", init_image.size, (0, 0, 0))  # all black (preserve image)
draw = ImageDraw.Draw(mask_image)

# Draw a white rectangle on the wall area (x1, y1, x2, y2)
draw.rectangle([180, 120, 330, 250], fill=(255, 255, 255))  # adjust coords for your wall

mask_image.save(mask_path)
print("✅ Mask saved as mask.png")

# ---------- LOAD MASK ----------
mask_image = Image.open(mask_path).convert("RGB").resize((512, 512))

# ---------- GENERATE EDITED IMAGE ----------
result = pipe(
    prompt=prompt,
    image=init_image,
    mask_image=mask_image,
    guidance_scale=8.0,
    num_inference_steps=50,
)

# ---------- SAVE & SHOW RESULT ----------
edited_image = result.images[0]
edited_image.save("edited_room.png")
edited_image.show()

print("🎉 Done! Saved as edited_room.png")
