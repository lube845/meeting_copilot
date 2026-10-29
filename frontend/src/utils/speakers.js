/**
 * 说话人替换工具（lift 自 streamlit_app.py:210-262）
 */

/**
 * 替换转写文本中的"说话人N"为真实姓名
 * @param {string} content - 转写 Markdown 内容
 * @param {string[]} speakerNames - 参会人员姓名列表
 * @param {string[]} speakerTitles - 参会人员职称列表
 * @returns {string}
 */
export function replaceSpeakerNames(content, speakerNames, speakerTitles) {
  if (!content) return ''
  let result = content
  // 用 (?!\\d) 防止「说话人1」把「说话人10/11/...」一起吃掉
  for (let i = 0; i < speakerNames.length; i++) {
    const name = (speakerNames[i] || '').trim()
    const title = (speakerTitles[i] || '').trim()
    if (name || title) {
      const full = title ? `${name}(${title})` : name
      const re = new RegExp(`说话人${i}(?!\\d)`, 'g')
      result = result.replace(re, full)
    }
  }
  return result
}

/**
 * 构建说话人映射字符串（用于 prompt 中的说话人参考）
 * @param {string[]} speakerNames
 * @param {string[]} speakerTitles
 * @param {number} cnt
 * @returns {string}
 */
export function buildSpeakerMap(speakerNames, speakerTitles, cnt) {
  const lines = []
  for (let i = 0; i < cnt; i++) {
    const name = ((speakerNames[i] || '')).trim()
    const title = ((speakerTitles[i] || '')).trim()
    if (name || title) {
      const full = title ? `${name}(${title})` : name
      lines.push(`说话人${i} -> ${full}`)
    } else {
      lines.push(`说话人${i} -> 说话人${i}`)
    }
  }
  return lines.join('\n')
}

/**
 * 格式化参会人员列表为字符串
 * @param {string[]} speakerNames
 * @param {string[]} speakerTitles
 * @returns {string}
 */
export function formatParticipants(speakerNames, speakerTitles) {
  const list = []
  for (let i = 0; i < speakerNames.length; i++) {
    const name = (speakerNames[i] || '').trim()
    const title = (speakerTitles[i] || '').trim()
    if (name || title) {
      const full = title ? `${name}(${title})` : name
      list.push(full)
    }
  }
  return list.length ? list.join(', ') : '未填写'
}