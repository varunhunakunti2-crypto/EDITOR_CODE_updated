# ---------- INSTALL REQUIRED LIBRARIES ----------
# pip install diffusers transformers accelerate torch torchvision safetensors pillow

import torch
from diffusers import StableDiffusionInpaintPipeline
from PIL import Image

# ---------- LOAD THE MODEL ----------
model_id = "stabilityai/stable-diffusion-2-inpainting"

# Load the inpainting pipeline (it works fine even without a mask)
pipe = StableDiffusionInpaintPipeline.from_pretrained(
    model_id,
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
)
pipe = pipe.to("cuda" if torch.cuda.is_available() else "cpu")

# ---------- USER INPUTS ----------
image_path = "test.jpg"  # Path to your input image
prompt = "add television on the wall for this input image."

# ---------- LOAD THE INPUT IMAGE ----------
init_image = Image.open(image_path).convert("RGB").resize((512, 512))

# ---------- CREATE A BLANK WHITE MASK (EDIT ENTIRE IMAGE) ----------
mask_image = Image.new("RGB", init_image.size, (255, 255, 255))

# ---------- GENERATE THE EDITED IMAGE ----------
result = pipe(
    prompt=prompt,
    image=init_image,
    mask_image=mask_image,
    guidance_scale=8.0,   # how strongly the prompt affects the result (7–9 recommended)
    num_inference_steps=50,  # higher = more detail (but slower)
)

# ---------- SAVE AND DISPLAY THE RESULT ----------
edited_image = result.images[0]
edited_image.save("edited_room.png")
edited_image.show()

print("✅ Image editing complete — saved as edited_room.png")