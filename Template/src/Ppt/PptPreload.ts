export interface PreloadProgress {
  ready: Set<string>
  failed: number
  total: number
}

/** 逐页预取并解码，同一 URL 供主预览和缩略图复用。 */
export function preloadPptImages(
  urls: string[],
  onProgress: (progress: PreloadProgress) => void,
  priority: () => string[] = () => [],
) {
  const pending = [...new Set(urls)]
  const total = pending.length
  const ready = new Set<string>()
  const images = new Set<HTMLImageElement>()
  let current: HTMLImageElement | undefined
  let failed = 0
  let stopped = false

  function progress() { onProgress({ ready: new Set(ready), failed, total }) }

  function next() {
    if (stopped || !pending.length) return
    const preferred = priority().find((url) => pending.includes(url))
    const position = preferred ? pending.indexOf(preferred) : 0
    const url = pending.splice(position, 1)[0]
    const image = new Image()
    current = image
    images.add(image)
    image.decoding = 'async'
    image.onload = async () => {
      // 提前解码，翻页时无需再等待图片解码完成。
      try { await image.decode?.() } catch { /* 已加载图片由浏览器在绘制时解码 */ }
      if (stopped) return
      ready.add(url)
      image.onload = image.onerror = null
      current = undefined
      progress()
      next()
    }
    image.onerror = () => {
      if (stopped) return
      failed += 1
      images.delete(image)
      image.onload = image.onerror = null
      current = undefined
      progress()
      next()
    }
    image.src = url
  }

  progress()
  next()
  return () => {
    stopped = true
    if (current) {
      current.onload = current.onerror = null
      current.removeAttribute('src')
    }
    // 文稿切换或刷新时释放上一批图片，不把所有历史文稿留在浏览器内存中。
    images.clear()
  }
}
