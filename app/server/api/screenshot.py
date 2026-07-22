"""
截图压缩服务
前端截图传到后端，用 Pillow 压缩到指定大小
"""
import io
import base64
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/screenshot", tags=["screenshot"])


class CompressRequest(BaseModel):
    image_data: str  # base64 编码的图片数据
    max_size_kb: int = 500  # 目标最大大小(KB)
    quality: int = 85  # 初始JPEG质量


@router.post("/compress")
def compress_screenshot(req: CompressRequest):
    """压缩截图到指定大小"""
    try:
        from PIL import Image

        # 解码 base64
        if ',' in req.image_data:
            image_data = req.image_data.split(',', 1)[1]
        else:
            image_data = req.image_data

        image_bytes = base64.b64decode(image_data)
        img = Image.open(io.BytesIO(image_bytes))

        # 转为RGB（去掉alpha通道，JPEG不支持）
        if img.mode in ('RGBA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[3] if len(img.split()) == 4 else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # 逐步降低质量直到达到目标大小
        max_bytes = req.max_size_kb * 1024
        quality = req.quality
        output = io.BytesIO()

        while quality > 10:
            output.seek(0)
            output.truncate()
            img.save(output, format='JPEG', quality=quality, optimize=True)
            size = output.tell()
            if size <= max_bytes:
                break
            quality -= 5

        # 如果质量降到最低还是太大，缩小尺寸
        if output.tell() > max_bytes:
            while output.tell() > max_bytes and img.size[0] > 800:
                new_width = int(img.size[0] * 0.8)
                new_height = int(img.size[1] * 0.8)
                img = img.resize((new_width, new_height), Image.LANCZOS)
                output.seek(0)
                output.truncate()
                img.save(output, format='JPEG', quality=quality, optimize=True)

        output.seek(0)
        size_kb = round(output.tell() / 1024)
        logger.info(f"[截图压缩] 原始{len(image_bytes)//1024}KB → 压缩后{size_kb}KB (质量{quality})")

        return StreamingResponse(
            io.BytesIO(output.read()),
            media_type='image/jpeg',
            headers={
                'Content-Disposition': f'attachment; filename="screenshot_{size_kb}kb.jpg"',
                'X-Original-Size': str(len(image_bytes) // 1024),
                'X-Compressed-Size': str(size_kb),
            }
        )
    except Exception as e:
        logger.error(f"截图压缩失败: {e}")
        raise HTTPException(status_code=500, detail=f"压缩失败: {str(e)}")
