import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = path.resolve(__dirname, "../oah/apps/web/dist");
const API_TARGET = "http://127.0.0.1:8787";
const PORT = 5173;

const MIME_TYPES = {
  ".html": "text/html",
  ".js": "application/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
};

const API_SUFFIXES = ["/api/", "/internal/", "/healthz", "/readyz", "/metrics"];

/**
 * Detect if the request URL targets an API path, possibly behind a reverse-proxy prefix.
 * e.g. /ws-xxx/proxy/5173/api/v1/workspaces -> proxy to /api/v1/workspaces
 * e.g. /api/v1/workspaces -> proxy to /api/v1/workspaces
 */
function matchApiPath(url) {
  for (const suffix of API_SUFFIXES) {
    const idx = url.indexOf(suffix);
    if (idx !== -1) {
      const apiPath = url.slice(idx);
      const prefix = url.slice(0, idx);
      return { prefix, apiPath };
    }
  }
  return null;
}

function proxyRequest(req, res, apiPath) {
  const url = new URL(apiPath, API_TARGET);

  const options = {
    hostname: "127.0.0.1",
    port: 8787,
    path: url.pathname + url.search,
    method: req.method,
    headers: { ...req.headers, host: "127.0.0.1:8787" },
  };

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res, { end: true });
  });

  proxyReq.on("error", (err) => {
    console.error("Proxy error:", err.message);
    res.writeHead(502);
    res.end("Bad Gateway");
  });

  req.pipe(proxyReq, { end: true });
}

function serveStatic(req, res, prefix) {
  // Strip the proxy prefix from the file path
  let filePath = req.url.split("?")[0];
  if (prefix && filePath.startsWith(prefix)) {
    filePath = filePath.slice(prefix.length) || "/";
  }

  // SPA fallback: non-file requests serve index.html
  if (filePath === "/" || !path.extname(filePath)) {
    filePath = "/index.html";
  }

  const fullPath = path.join(STATIC_DIR, filePath);

  if (!fullPath.startsWith(STATIC_DIR)) {
    res.writeHead(403);
    return res.end("Forbidden");
  }

  fs.readFile(fullPath, (err, data) => {
    if (err) {
      fs.readFile(path.join(STATIC_DIR, "index.html"), (e2, idx) => {
        if (e2) {
          res.writeHead(404);
          return res.end("Not Found");
        }
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end(injectConfig(idx, prefix));
      });
      return;
    }

    const ext = path.extname(fullPath);
    const mime = MIME_TYPES[ext] || "application/octet-stream";
    const isHtml = ext === ".html";
    res.writeHead(200, { "Content-Type": mime });
    res.end(isHtml ? injectConfig(data, prefix) : data);
  });
}

function injectConfig(html, prefix) {
  const str = typeof html === "string" ? html : html.toString("utf8");
  const token = process.env.OAH_LOCAL_API_TOKEN || "";
  // Build baseUrl: origin + path prefix (if any) so API requests use the right base
  // e.g. with prefix "/ws-xxx/proxy/5173" -> baseUrl = "https://host/ws-xxx/proxy/5173"
  const prefixJson = JSON.stringify(prefix || "");
  const inject = `<script>
    (function(){
      try {
        var key = "oah.web.connection";
        var existing = window.localStorage.getItem(key);
        var conn = existing ? JSON.parse(existing) : {};
        var prefix = ${prefixJson};
        var base = window.location.origin + (prefix || window.location.pathname.replace(/\\/$/,""));
        conn.baseUrl = base;
        conn.token = ${JSON.stringify(token)};
        window.localStorage.setItem(key, JSON.stringify(conn));
      } catch(e){}
    })();
  </script>`;
  return str.replace("</head>", inject + "</head>");
}

const server = http.createServer((req, res) => {
  const match = matchApiPath(req.url);
  if (match) {
    proxyRequest(req, res, match.apiPath);
  } else {
    // Detect prefix from the first request's Referer or path pattern
    const prefix = detectPrefix(req.url);
    serveStatic(req, res, prefix);
  }
});

/**
 * Try to detect the reverse-proxy path prefix from the request URL.
 * If the URL looks like /ws-xxx/proxy/5173/assets/..., extract /ws-xxx/proxy/5173 as prefix.
 */
function detectPrefix(url) {
  // Look for a pattern like /<something>/proxy/<port>/
  const m = url.match(/^(\/[^/]+\/proxy\/\d+)\//);
  return m ? m[1] : "";
}

server.listen(PORT, "0.0.0.0", () => {
  console.log(`OAH WebUI serving on http://0.0.0.0:${PORT}`);
  console.log(`  Static files: ${STATIC_DIR}`);
  console.log(`  API proxy:    ${API_TARGET}`);
});
