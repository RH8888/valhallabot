import { createServer } from 'node:http'
import { stat, readFile } from 'node:fs/promises'
import { extname, join, normalize, sep } from 'node:path'

const distDir = join(process.cwd(), 'dist')
const defaultBase = '/'

function normalizeBase(value) {
  if (!value) {
    return defaultBase
  }
  let base = value.trim()
  if (!base.startsWith('/')) {
    base = `/${base}`
  }
  if (base !== '/' && base.endsWith('/')) {
    base = base.slice(0, -1)
  }
  return base || defaultBase
}

const basePath = normalizeBase(process.env.DASHBOARD_BASE_URL)
const basePrefix = basePath === '/' ? '/' : `${basePath}/`

const mimeTypes = new Map([
  ['.css', 'text/css'],
  ['.js', 'application/javascript'],
  ['.mjs', 'application/javascript'],
  ['.cjs', 'application/javascript'],
  ['.json', 'application/json'],
  ['.html', 'text/html'],
  ['.svg', 'image/svg+xml'],
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.gif', 'image/gif'],
  ['.webp', 'image/webp'],
  ['.ico', 'image/x-icon'],
  ['.woff', 'font/woff'],
  ['.woff2', 'font/woff2'],
])

function getMimeType(filePath) {
  return mimeTypes.get(extname(filePath).toLowerCase()) || 'application/octet-stream'
}

function sanitizePath(pathname) {
  let normalized = normalize(pathname)
  while (normalized.startsWith(`..${sep}`) || normalized === '..') {
    normalized = normalized.slice(3)
  }
  if (normalized.startsWith(sep)) {
    normalized = normalized.slice(1)
  }
  return normalized
}

const port = Number.parseInt(process.env.PORT || '4173', 10)

const server = createServer(async (req, res) => {
  try {
    const method = req.method ?? 'GET'
    if (method !== 'GET' && method !== 'HEAD') {
      res.statusCode = 405
      res.setHeader('Allow', 'GET, HEAD')
      res.end('Method Not Allowed')
      return
    }

    if (!req.url) {
      res.statusCode = 400
      res.end('Bad Request')
      return
    }

    const [rawPath] = req.url.split('?')
    let requestPath = decodeURIComponent(rawPath)

    if (basePath !== '/' && requestPath === basePath) {
      res.statusCode = 301
      res.setHeader('Location', `${basePath}/`)
      res.end()
      return
    }

    if (!requestPath.startsWith(basePrefix)) {
      res.statusCode = 404
      res.end('Not Found')
      return
    }

    let relativePath = basePath === '/' ? requestPath : requestPath.slice(basePath.length)
    if (relativePath.startsWith('/')) {
      relativePath = relativePath.slice(1)
    }
    const safePath = sanitizePath(relativePath)

    let filePath = join(distDir, safePath)
    let fileStat

    try {
      fileStat = await stat(filePath)
      if (fileStat.isDirectory()) {
        filePath = join(filePath, 'index.html')
        fileStat = await stat(filePath)
      }
    } catch (error) {
      filePath = join(distDir, 'index.html')
      fileStat = await stat(filePath)
    }

    const body = await readFile(filePath)
    res.statusCode = 200
    res.setHeader('Content-Type', getMimeType(filePath))
    res.setHeader('Content-Length', body.length)
    if (method === 'HEAD') {
      res.end()
    } else {
      res.end(body)
    }
  } catch (error) {
    res.statusCode = 500
    res.end('Internal Server Error')
    console.error('Dashboard server error:', error)
  }
})

server.listen(port, '0.0.0.0', () => {
  console.log(`Dashboard listening on port ${port} with base path '${basePath}'`)
})
