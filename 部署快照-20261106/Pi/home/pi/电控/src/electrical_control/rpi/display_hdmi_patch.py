# 临时补丁：跳过渲染
import sys
original_file = sys.argv[1]
with open(original_file, 'r') as f:
    content = f.read()
# 在_compose_frame开头直接返回空白图片
content = content.replace(
    'def _compose_frame(self, view: DisplayViewModel) -> Image.Image:',
    'def _compose_frame(self, view: DisplayViewModel) -> Image.Image:\n        from PIL import Image as PILImage\n        return PILImage.new("RGB", (1024, 600), (0, 0, 0))'
)
with open(original_file, 'w') as f:
    f.write(content)
