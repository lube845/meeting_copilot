/**
 * 浏览器文件下载辅助（导出 Word 等场景）
 */

/**
 * 触发浏览器下载一个 Blob / 字节流
 * @param {Blob | ArrayBuffer} data
 * @param {string} filename - 下载文件名
 * @param {string} mime - MIME 类型
 */
export function downloadFile(data, filename, mime = 'application/octet-stream') {
  const blob = data instanceof Blob ? data : new Blob([data], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}