from openai import OpenAI
import os
import base64

output_dir = "/inspire/hdd/project/ai4education/bishuzhen-CZXS24220022/edubench/TheoremExplainAgent/output/svg_test"
os.makedirs(output_dir, exist_ok=True)

client = OpenAI(base_url="http://localhost:8000/v1", api_key="dummy")

# Try loading the original problem image
img_path = "/inspire/hdd/project/ai4education/bishuzhen-CZXS24220022/edubench/TheoremExplainAgent/output/exp_gemini-3-pro-preview/problem_23_chemistry_g12/problem_diagram.png"
img_content = None
if os.path.exists(img_path) and os.path.getsize(img_path) > 0:
    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    img_content = {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
    print("Image loaded")
else:
    print("Image empty/missing, text-only prompt")

prompt = '''You are an expert SVG/HTML developer specializing in scientific diagrams. Generate a SINGLE self-contained HTML file. Output ONLY code starting with <!DOCTYPE html> and ending with </html>. No explanation, no markdown.

## Task
Render TWO chemistry diagrams side-by-side in one HTML page:
- LEFT: H₂O₂ molecule 3D "open book" structure
- RIGHT: Crystal X unit cell (cube with alternating ions at corners)

---

## LEFT DIAGRAM — H₂O₂ Molecule (SVG, 380x340, white background)

Draw an isometric/perspective view of the H₂O₂ "open book" shape:

### Atoms (draw as filled circles with stroke):
- O1: center (190, 155), r=22, fill=#cc2200, stroke=#880000, stroke-width=2  [left oxygen]
- O2: center (230, 175), r=22, fill=#cc2200, stroke=#880000, stroke-width=2  [right oxygen]
- H1: center (130, 105), r=13, fill=#e8e8e8, stroke=#888, stroke-width=1.5  [upper-left hydrogen]
- H2: center (300, 230), r=13, fill=#e8e8e8, stroke=#888, stroke-width=1.5  [lower-right hydrogen]

### Bonds (draw BEHIND atoms, z-order matters):
- O-O bond (non-polar): line from O1 center to O2 center, stroke=#666, stroke-width=5
- H1-O1 bond (polar): line from H1 center to O1 center, stroke=#666, stroke-width=4
- H2-O2 bond (polar): line from H2 center to O2 center, stroke=#666, stroke-width=4

### Dihedral angle guide planes (light dashed rectangles to show "open book"):
- Left plane: dashed rect roughly through H1, O1, O2, light blue fill opacity=0.08, stroke=#4488cc stroke-dasharray="5,4"
  Points: polygon (110,80) (175,120) (250,155) (185,115)
- Right plane: dashed rect roughly through O1, O2, H2, light green fill opacity=0.08, stroke=#44aa66 stroke-dasharray="5,4"
  Points: polygon (175,120) (250,155) (320,215) (245,175)

### Dipole moment arrows (blue, from H toward O along bond direction):
- Arrow on H1-O1: from (145,115) to (170,135), stroke=#2255cc, stroke-width=2, arrowhead at end
- Arrow on H2-O2: from (285,220) to (255,200), stroke=#2255cc, stroke-width=2, arrowhead at end

### Labels:
- "O" near O1: x=160, y=148, font-size=15, fill=#cc2200, font-weight=bold
- "O" near O2: x=258, y=168, font-size=15, fill=#cc2200, font-weight=bold
- "H" near H1: x=108, y=98, font-size=13, fill=#555
- "H" near H2: x=316, y=236, font-size=13, fill=#555
- "O–O (non-polar bond)" label: x=195, y=145, font-size=10, fill=#444, font-style=italic
- "O–H (polar bond)" ×2: one near each O-H bond midpoint, font-size=10, fill=#444, font-style=italic
- Title: "H₂O₂ Molecular Structure" at top center x=190, y=28, font-size=15, font-weight=bold, fill=#222

---

## RIGHT DIAGRAM — Crystal X Unit Cell (SVG, 380x340, white background)

Draw a 3D perspective cube (isometric-style) with 8 spheres at the corners, alternating black (A) and white (B).

### Cube wireframe (isometric projection):
Use these 8 corner pixel coordinates for a cube of side ~130px:
- Front-bottom-left  (FBL): (100, 250)
- Front-bottom-right (FBR): (220, 250)
- Front-top-left     (FTL): (100, 130)
- Front-top-right    (FTR): (220, 130)
- Back-bottom-left   (BBL): (145, 285)  [FBL + offset (45,35)]
- Back-bottom-right  (BBR): (265, 285)
- Back-top-left      (BTL): (145, 165)
- Back-top-right     (BTR): (265, 165)

Draw 12 edges:
- Front face: FBL-FBR, FBR-FTR, FTR-FTL, FTL-FBL  (solid black, stroke-width=2)
- Back face: BBL-BBR, BBR-BTR, BTR-BTL, BTL-BBL  (dashed gray, stroke-dasharray="5,3")
- Depth edges: FBL-BBL, FBR-BBR, FTL-BTL, FTR-BTR  (solid for visible, dashed for hidden)
  - FBR-BBR and FTR-BTR: solid
  - FBL-BBL and FTL-BTL: dashed gray

### Atoms at corners (draw on top of edges, r=14):
Alternating pattern — A (black) and B (white) at adjacent corners:
- FBL (100,250): A — fill=#111, stroke=#000
- FBR (220,250): B — fill=#fff, stroke=#333
- FTL (100,130): B — fill=#fff, stroke=#333
- FTR (220,130): A — fill=#111, stroke=#000
- BBL (145,285): B — fill=#fff, stroke=#333
- BBR (265,285): A — fill=#111, stroke=#000
- BTL (145,165): A — fill=#111, stroke=#000
- BTR (265,165): B — fill=#fff, stroke=#333

### Legend (below the cube):
- Small circle r=7 fill=#111 at (130,320), label "A ion" at (145,320)
- Small circle r=7 fill=#fff stroke=#333 at (215,320), label "B ion" at (230,320)
All label font-size=13, fill=#222

### Title: "Crystal X Unit Cell" at x=190, y=28, font-size=15, font-weight=bold, fill=#222

---

## HTML Page Layout
- Page background: #f5f5f5
- Two SVGs side by side in a flex row, each in a white card with subtle border-radius and box-shadow
- Page title: "Problem 23 Chemistry — H₂O₂ & Crystal X"
- Caption under each diagram

Output complete HTML now:'''

if img_content:
    user_content = [
        img_content,
        {"type": "text", "text": "Reference image above shows the original problem diagram.\n\n" + prompt}
    ]
else:
    user_content = [{"type": "text", "text": prompt}]

messages = [{"role": "user", "content": user_content}]

print("Calling model...")
response = client.chat.completions.create(
    model="gemini-3.1-pro-preview",
    messages=messages,
    temperature=0.1,
)

html_code = response.choices[0].message.content.strip()

if "<!DOCTYPE" in html_code:
    html_code = html_code[html_code.index("<!DOCTYPE"):]
if html_code.endswith("```"):
    html_code = html_code[:-3].rstrip()

output_path = os.path.join(output_dir, "problem_23_chemistry_g12_scene1.html")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(html_code)

print(f"Saved to: {output_path}")
print(f"File size: {len(html_code)} chars")
print("--- First 200 chars ---")
print(html_code[:200])
