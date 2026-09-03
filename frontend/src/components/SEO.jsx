import { useEffect } from 'react'

// Central place for the site's canonical domain + fallback share image, so
// every page's Open Graph/Twitter tags resolve to real, absolute URLs (both
// platforms ignore relative image/url paths).
const SITE_NAME = 'JobBeggar'
const SITE_URL = 'https://jobbeggar.com'
const DEFAULT_IMAGE = `${SITE_URL}/images/og-cover.png`

// Finds an existing <meta> tag by attribute (name or property) and updates
// its content, or creates one if it doesn't exist yet. Keeps index.html's
// static defaults intact for the very first paint / non-JS fetches, then
// swaps in the page-specific values once React mounts.
function upsertMeta(attr, key, content) {
  if (!content) return
  let el = document.head.querySelector(`meta[${attr}="${key}"]`)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attr, key)
    document.head.appendChild(el)
  }
  el.setAttribute('content', content)
}

function upsertLink(rel, href) {
  if (!href) return
  let el = document.head.querySelector(`link[rel="${rel}"]`)
  if (!el) {
    el = document.createElement('link')
    el.setAttribute('rel', rel)
    document.head.appendChild(el)
  }
  el.setAttribute('href', href)
}

/**
 * Drop <SEO /> at the top of any page component (right before <Navbar />)
 * to set that page's <title>, meta description, canonical link, and
 * Open Graph/Twitter Card tags.
 *
 * Note: this is a client-side-rendered SPA with a single served index.html,
 * so link-unfurling bots that DON'T execute JS (Slack, Twitter/X, LinkedIn,
 * iMessage) will still only ever see the site-wide defaults baked into
 * index.html -- true per-page preview cards on shared links would need
 * server-side rendering or prerendering. This component *does* fully cover
 * per-page <title>/description for real browsers and JS-rendering crawlers
 * like Googlebot, which is what actually drives search-result CTR.
 */
export default function SEO({ title, description, path = '/', image = DEFAULT_IMAGE }) {
  useEffect(() => {
    const fullTitle = title || SITE_NAME
    const url = `${SITE_URL}${path}`

    document.title = fullTitle

    upsertMeta('name', 'description', description)
    upsertLink('canonical', url)

    upsertMeta('property', 'og:site_name', SITE_NAME)
    upsertMeta('property', 'og:type', 'website')
    upsertMeta('property', 'og:title', fullTitle)
    upsertMeta('property', 'og:description', description)
    upsertMeta('property', 'og:url', url)
    upsertMeta('property', 'og:image', image)

    upsertMeta('name', 'twitter:card', 'summary_large_image')
    upsertMeta('name', 'twitter:title', fullTitle)
    upsertMeta('name', 'twitter:description', description)
    upsertMeta('name', 'twitter:image', image)
  }, [title, description, path, image])

  return null
}
