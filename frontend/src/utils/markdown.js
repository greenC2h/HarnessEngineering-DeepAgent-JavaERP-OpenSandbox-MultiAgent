import DOMPurify from "dompurify";
import { marked } from "marked";


const MARKDOWN_ALLOWED_TAGS = [
  "a",
  "b",
  "blockquote",
  "br",
  "code",
  "del",
  "em",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "i",
  "input",
  "li",
  "ol",
  "p",
  "pre",
  "s",
  "strong",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "ul",
];

const MARKDOWN_ALLOWED_ATTRIBUTES = [
  "checked",
  "disabled",
  "href",
  "title",
  "type",
];


/**
 * 将不可信的模型输出解析为适合插入消息区域的安全 Markdown HTML。
 *
 * @param {string} content - 模型或 Agent 返回的原始 Markdown 文本。
 * @returns {string} 已清洗、可用于 v-html 的 HTML。
 */
export function renderMarkdown(content) {
  const parsedHtml = marked.parse(content || "", {
    breaks: true,
    gfm: true,
  });
  return DOMPurify.sanitize(parsedHtml, {
    ALLOWED_ATTR: MARKDOWN_ALLOWED_ATTRIBUTES,
    ALLOWED_TAGS: MARKDOWN_ALLOWED_TAGS,
    FORBID_ATTR: ["style"],
  });
}
