/**
 * 安全的 Markdown 渲染：marked + DOMPurify
 *
 * 用法：v-html="renderMarkdown(text)"
 *
 * 为什么不直接用 marked：marked 默认不净化 HTML，
 * LLM 输出 / ASR 转写里若夹带 <script>、<img onerror=> 等会被直接执行。
 * DOMPurify 在不破坏正常格式的前提下剥离危险节点/属性。
 */
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({
  // marked 默认会对 HTML token 做转义；这里保留原始以便 DOMPurify 二次过滤
  // （避免双重 escape 导致代码块里的 < 变成 &lt;）
  gfm: true,
  breaks: true,
})

export function renderMarkdown(md) {
  if (!md) return ''
  const html = marked.parse(md)
  return DOMPurify.sanitize(html, {
    ADD_ATTR: ['target'],
  })
}