/**
 * useScreenshot - 截图 Hook
 * 封装 html-to-image 截图逻辑
 */
import { useState, useCallback } from 'react'
import { message } from 'antd'

/**
 * 截图 Hook
 * @param {Object} options - 配置选项
 * @param {string} options.filename - 下载文件名前缀
 * @param {number} options.pixelRatio - 像素比例（默认 2）
 */
export function useScreenshot(options = {}) {
  const {
    filename = 'screenshot',
    pixelRatio = 2
  } = options

  const [isCapturing, setIsCapturing] = useState(false)

  // 截图并下载
  const capture = useCallback(async (elementRef, customFilename) => {
    if (!elementRef?.current) {
      message.error('截图元素不存在')
      return
    }

    setIsCapturing(true)

    try {
      const { toPng } = await import('html-to-image')
      const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '')
      const fileName = `${customFilename || filename}_${dateStr}.png`

      const dataUrl = await toPng(elementRef.current, {
        pixelRatio,
        backgroundColor: '#ffffff'
      })

      // 创建下载链接
      const link = document.createElement('a')
      link.download = fileName
      link.href = dataUrl
      link.click()

      message.success('截图已保存')
    } catch (error) {
      console.error('[useScreenshot] 截图失败:', error)
      message.error('截图失败')
    } finally {
      setIsCapturing(false)
    }
  }, [filename, pixelRatio])

  // 截图到剪贴板
  const copyToClipboard = useCallback(async (elementRef) => {
    if (!elementRef?.current) {
      message.error('截图元素不存在')
      return
    }

    setIsCapturing(true)

    try {
      const { toBlob } = await import('html-to-image')
      const blob = await toBlob(elementRef.current, {
        pixelRatio,
        backgroundColor: '#ffffff'
      })

      await navigator.clipboard.write([
        new ClipboardItem({ 'image/png': blob })
      ])

      message.success('截图已复制到剪贴板')
    } catch (error) {
      console.error('[useScreenshot] 复制失败:', error)
      message.error('复制失败')
    } finally {
      setIsCapturing(false)
    }
  }, [pixelRatio])

  return {
    isCapturing,
    capture,
    copyToClipboard
  }
}

export default useScreenshot
