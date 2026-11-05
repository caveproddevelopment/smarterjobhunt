// Rich-text editor for The JobBeggar Brief (admins only). Bold, italic,
// underline, headings, lists, quotes, links, font family / size / weight and
// colour. Output HTML is sanitized again on the server (backend/blog_html.py)
// and on display (BlogParts.jsx), so only those formats ever reach readers.
import { Extension } from '@tiptap/core'
import { EditorContent, useEditor, useEditorState } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { Color, FontFamily, FontSize, TextStyle } from '@tiptap/extension-text-style'

const FontWeight = Extension.create({
  name: 'fontWeight',
  addGlobalAttributes() {
    return [{
      types: ['textStyle'],
      attributes: {
        fontWeight: {
          default: null,
          parseHTML: (el) => el.style.fontWeight || null,
          renderHTML: (attrs) => (attrs.fontWeight ? { style: `font-weight: ${attrs.fontWeight}` } : {}),
        },
      },
    }]
  },
  addCommands() {
    return {
      setFontWeight: (fontWeight) => ({ chain }) => chain().setMark('textStyle', { fontWeight }).run(),
      unsetFontWeight: () => ({ chain }) =>
        chain().setMark('textStyle', { fontWeight: null }).removeEmptyTextStyle().run(),
    }
  },
})

const FONT_FAMILIES = [
  ['', 'Default font'],
  ['Inter, sans-serif', 'Inter'],
  ['"Bricolage Grotesque", sans-serif', 'Bricolage'],
  ['Georgia, serif', 'Georgia (serif)'],
  ['"Times New Roman", serif', 'Times New Roman'],
  ['Arial, sans-serif', 'Arial'],
  ['"JetBrains Mono", monospace', 'Monospace'],
]
const FONT_SIZES = ['', '14px', '16px', '18px', '20px', '24px', '30px', '36px', '48px']
const FONT_WEIGHTS = [['', 'Weight'], ['300', 'Light'], ['400', 'Regular'], ['500', 'Medium'],
  ['600', 'Semibold'], ['700', 'Bold'], ['800', 'Extra bold']]
const SWATCHES = ['#1B1D22', '#565A63', '#E24B34', '#F2872E', '#C99A06', '#2E9E63', '#2F6FB0', '#7A3EB1']

function Btn({ active, onClick, title, children, disabled }) {
  return (
    <button type="button" title={title} aria-label={title} aria-pressed={active} disabled={disabled}
      onMouseDown={(e) => e.preventDefault()} onClick={onClick}
      className={`flex h-8 min-w-8 items-center justify-center rounded-md px-2 text-sm transition-colors disabled:opacity-40 ${
        active ? 'bg-ink text-white' : 'text-ink hover:bg-mist'
      }`}>
      {children}
    </button>
  )
}

const selectCls = 'h-8 rounded-md border border-line bg-white px-2 text-xs text-ink outline-none focus:border-ember'

function Toolbar({ editor }) {
  const s = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e.isActive('bold'), italic: e.isActive('italic'), underline: e.isActive('underline'),
      strike: e.isActive('strike'), h2: e.isActive('heading', { level: 2 }), h3: e.isActive('heading', { level: 3 }),
      bullet: e.isActive('bulletList'), ordered: e.isActive('orderedList'), quote: e.isActive('blockquote'),
      link: e.isActive('link'),
      family: e.getAttributes('textStyle').fontFamily || '',
      size: e.getAttributes('textStyle').fontSize || '',
      weight: e.getAttributes('textStyle').fontWeight || '',
      color: e.getAttributes('textStyle').color || '',
    }),
  })
  const c = () => editor.chain().focus()

  function onLink() {
    if (s.link) {
      c().extendMarkRange('link').unsetLink().run()
      return
    }
    const url = window.prompt('Link address (https://...)', 'https://')
    if (!url || url === 'https://') return
    const href = /^(https?:\/\/|mailto:)/i.test(url) ? url : `https://${url}`
    if (editor.state.selection.empty) {
      c().insertContent({ type: 'text', text: url, marks: [{ type: 'link', attrs: { href } }] }).run()
    } else {
      // move the cursor past the link so the next keystroke doesn't replace it
      const end = editor.state.selection.to
      c().extendMarkRange('link').setLink({ href, target: '_blank' }).setTextSelection(end).run()
    }
  }

  return (
    <div className="sticky top-0 z-10 flex flex-wrap items-center gap-1 rounded-t-xl border-b border-line bg-white/95 p-2 backdrop-blur">
      <Btn title="Bold" active={s.bold} onClick={() => c().toggleBold().run()}><b>B</b></Btn>
      <Btn title="Italic" active={s.italic} onClick={() => c().toggleItalic().run()}><i>I</i></Btn>
      <Btn title="Underline" active={s.underline} onClick={() => c().toggleUnderline().run()}><u>U</u></Btn>
      <Btn title="Strikethrough" active={s.strike} onClick={() => c().toggleStrike().run()}><s>S</s></Btn>
      <span className="mx-1 h-5 w-px bg-line" />
      <Btn title="Heading" active={s.h2} onClick={() => c().toggleHeading({ level: 2 }).run()}>H2</Btn>
      <Btn title="Subheading" active={s.h3} onClick={() => c().toggleHeading({ level: 3 }).run()}>H3</Btn>
      <Btn title="Bulleted list" active={s.bullet} onClick={() => c().toggleBulletList().run()}>&bull; List</Btn>
      <Btn title="Numbered list" active={s.ordered} onClick={() => c().toggleOrderedList().run()}>1. List</Btn>
      <Btn title="Quote" active={s.quote} onClick={() => c().toggleBlockquote().run()}>&ldquo;&rdquo;</Btn>
      <Btn title={s.link ? 'Remove link' : 'Add link'} active={s.link} onClick={onLink}>
        {s.link ? 'Unlink' : 'Link'}
      </Btn>
      <span className="mx-1 h-5 w-px bg-line" />
      <select aria-label="Font" className={selectCls} value={s.family}
        onChange={(e) => (e.target.value ? c().setFontFamily(e.target.value).run() : c().unsetFontFamily().run())}>
        {FONT_FAMILIES.map(([v, label]) => <option key={label} value={v}>{label}</option>)}
      </select>
      <select aria-label="Font size" className={selectCls} value={s.size}
        onChange={(e) => (e.target.value ? c().setFontSize(e.target.value).run() : c().unsetFontSize().run())}>
        {FONT_SIZES.map((v) => <option key={v || 'default'} value={v}>{v ? v.replace('px', '') : 'Size'}</option>)}
      </select>
      <select aria-label="Font weight" className={selectCls} value={s.weight}
        onChange={(e) => (e.target.value ? c().setFontWeight(e.target.value).run() : c().unsetFontWeight().run())}>
        {FONT_WEIGHTS.map(([v, label]) => <option key={label} value={v}>{label}</option>)}
      </select>
      <span className="mx-1 h-5 w-px bg-line" />
      {SWATCHES.map((col) => (
        <button key={col} type="button" title={`Colour ${col}`} aria-label={`Colour ${col}`}
          onMouseDown={(e) => e.preventDefault()} onClick={() => c().setColor(col).run()}
          className={`h-6 w-6 rounded-full border ${s.color.toLowerCase() === col.toLowerCase() ? 'ring-2 ring-ink ring-offset-1' : 'border-line'}`}
          style={{ background: col }} />
      ))}
      <label title="Custom colour" className="relative flex h-6 w-6 cursor-pointer items-center justify-center rounded-full border border-line text-[10px] text-ink-soft">
        +
        <input type="color" aria-label="Custom colour" className="absolute inset-0 cursor-pointer opacity-0"
          value={/^#[0-9a-f]{6}$/i.test(s.color) ? s.color : '#000000'}
          onChange={(e) => c().setColor(e.target.value).run()} />
      </label>
      <Btn title="Clear formatting" onClick={() => c().unsetAllMarks().clearNodes().run()}>Clear</Btn>
    </div>
  )
}

export default function RichEditor({ value, onChange }) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
        code: false,
        codeBlock: false,
        link: { openOnClick: false, autolink: true, defaultProtocol: 'https',
          protocols: ['http', 'https', 'mailto'], HTMLAttributes: { target: '_blank', rel: 'noopener noreferrer' } },
      }),
      TextStyle, Color, FontFamily, FontSize, FontWeight,
    ],
    content: value || '',
    editorProps: { attributes: { class: 'brief-content min-h-[320px] px-4 py-4 outline-none', 'aria-label': 'Post' } },
    onUpdate: ({ editor: e }) => onChange(e.isEmpty ? '' : e.getHTML(), e.getText()),
  })
  if (!editor) return null
  return (
    <div className="rounded-xl border border-line bg-white focus-within:border-ember">
      <Toolbar editor={editor} />
      <EditorContent editor={editor} />
    </div>
  )
}
