// A true canvas density heatmap for Leaflet, vendored rather than pulled from a
// CDN so the map keeps the project's offline-first promise (same reason the ONNX
// runtime is served from our own origin).
//
// This is a compact port of Leaflet.heat (Vladimir Agafonkin, BSD-2-Clause) with
// its simpleheat core inlined. It draws each weighted point as a blurred radial
// blob, sums overlapping blobs on an alpha canvas, then colourises by a gradient
// - so dense clusters of cases read as a smooth, finely-localised hot surface
// instead of snapping to a 5 km grid.
import L from 'leaflet'

function SimpleHeat(canvas) {
  this._canvas = canvas
  this._ctx = canvas.getContext('2d')
  this._width = canvas.width
  this._height = canvas.height
  this._max = 1
  this._data = []
}

SimpleHeat.prototype = {
  // Green → amber → orange → red, matching the map's intensity legend.
  defaultRadius: 25,
  defaultGradient: { 0.25: '#3f8f5f', 0.5: '#c9a227', 0.75: '#d97706', 1.0: '#b3261e' },

  data(data) {
    this._data = data
    return this
  },
  max(max) {
    this._max = max
    return this
  },
  clear() {
    this._data = []
    return this
  },
  radius(r, blur) {
    blur = blur === undefined ? 15 : blur
    const circle = (this._circle = document.createElement('canvas'))
    const ctx = circle.getContext('2d')
    const r2 = (this._r = r + blur)
    circle.width = circle.height = r2 * 2
    ctx.shadowOffsetX = ctx.shadowOffsetY = r2 * 2
    ctx.shadowBlur = blur
    ctx.shadowColor = 'black'
    ctx.beginPath()
    ctx.arc(-r2, -r2, r, 0, Math.PI * 2, true)
    ctx.closePath()
    ctx.fill()
    return this
  },
  resize() {
    this._width = this._canvas.width
    this._height = this._canvas.height
  },
  gradient(grad) {
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    const gradient = ctx.createLinearGradient(0, 0, 0, 256)
    canvas.width = 1
    canvas.height = 256
    for (const i in grad) gradient.addColorStop(+i, grad[i])
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, 1, 256)
    this._grad = ctx.getImageData(0, 0, 1, 256).data
    return this
  },
  draw(minOpacity) {
    if (!this._circle) this.radius(this.defaultRadius)
    if (!this._grad) this.gradient(this.defaultGradient)
    const ctx = this._ctx
    ctx.clearRect(0, 0, this._width, this._height)
    for (const p of this._data) {
      ctx.globalAlpha = Math.min(
        Math.max(p[2] / this._max, minOpacity === undefined ? 0.05 : minOpacity),
        1,
      )
      ctx.drawImage(this._circle, p[0] - this._r, p[1] - this._r)
    }
    const colored = ctx.getImageData(0, 0, this._width, this._height)
    this._colorize(colored.data, this._grad)
    ctx.putImageData(colored, 0, 0)
    return this
  },
  _colorize(pixels, gradient) {
    for (let i = 0, len = pixels.length, j; i < len; i += 4) {
      j = pixels[i + 3] * 4 // alpha of this pixel selects the gradient colour
      if (j) {
        pixels[i] = gradient[j]
        pixels[i + 1] = gradient[j + 1]
        pixels[i + 2] = gradient[j + 2]
      }
    }
  },
}

const HeatLayer = L.Layer.extend({
  initialize(latlngs, options) {
    this._latlngs = latlngs || []
    L.setOptions(this, options)
  },
  setLatLngs(latlngs) {
    this._latlngs = latlngs || []
    return this.redraw()
  },
  setOptions(options) {
    L.setOptions(this, options)
    if (this._heat) this._updateOptions()
    return this.redraw()
  },
  redraw() {
    if (this._heat && !this._frame && this._map && !this._map._animating) {
      this._frame = L.Util.requestAnimFrame(this._redraw, this)
    }
    return this
  },
  onAdd(map) {
    this._map = map
    if (!this._canvas) this._initCanvas()
    map._panes.overlayPane.appendChild(this._canvas)
    map.on('moveend', this._reset, this)
    if (map.options.zoomAnimation && L.Browser.any3d) map.on('zoomanim', this._animateZoom, this)
    this._reset()
  },
  onRemove(map) {
    map.getPanes().overlayPane.removeChild(this._canvas)
    map.off('moveend', this._reset, this)
    if (map.options.zoomAnimation && L.Browser.any3d) map.off('zoomanim', this._animateZoom, this)
  },
  addTo(map) {
    map.addLayer(this)
    return this
  },
  _initCanvas() {
    const canvas = (this._canvas = L.DomUtil.create(
      'canvas',
      'leaflet-heatmap-layer leaflet-layer',
    ))
    const originProp = L.DomUtil.testProp([
      'transformOrigin',
      'WebkitTransformOrigin',
      'msTransformOrigin',
    ])
    canvas.style[originProp] = '50% 50%'
    const size = this._map.getSize()
    canvas.width = size.x
    canvas.height = size.y
    const animated = this._map.options.zoomAnimation && L.Browser.any3d
    L.DomUtil.addClass(canvas, 'leaflet-zoom-' + (animated ? 'animated' : 'hide'))
    this._heat = new SimpleHeat(canvas)
    this._updateOptions()
  },
  _updateOptions() {
    this._heat.radius(this.options.radius || this._heat.defaultRadius, this.options.blur)
    if (this.options.gradient) this._heat.gradient(this.options.gradient)
    if (this.options.max) this._heat.max(this.options.max)
  },
  _reset() {
    const topLeft = this._map.containerPointToLayerPoint([0, 0])
    L.DomUtil.setPosition(this._canvas, topLeft)
    const size = this._map.getSize()
    if (this._heat._width !== size.x) {
      this._canvas.width = this._heat._width = size.x
    }
    if (this._heat._height !== size.y) {
      this._canvas.height = this._heat._height = size.y
    }
    this._redraw()
  },
  _redraw() {
    if (!this._map) return
    const data = []
    const r = this._heat._r
    const size = this._map.getSize()
    const bounds = new L.Bounds(L.point([-r, -r]), size.add([r, r]))
    const max = this.options.max === undefined ? 1 : this.options.max
    const maxZoom = this.options.maxZoom === undefined ? this._map.getMaxZoom() : this.options.maxZoom
    const v = 1 / Math.pow(2, Math.max(0, Math.min(maxZoom - this._map.getZoom(), 12)) / 2)
    const cellSize = r / 2
    const grid = []
    const panePos = this._map._getMapPanePos()
    const offsetX = panePos.x % cellSize
    const offsetY = panePos.y % cellSize

    for (let i = 0, len = this._latlngs.length; i < len; i++) {
      const ll = this._latlngs[i]
      const p = this._map.latLngToContainerPoint(ll)
      if (!bounds.contains(p)) continue
      const x = Math.floor((p.x - offsetX) / cellSize) + 2
      const y = Math.floor((p.y - offsetY) / cellSize) + 2
      const alt = ll.alt !== undefined ? ll.alt : ll[2] !== undefined ? +ll[2] : 1
      const k = alt * v
      grid[y] = grid[y] || []
      const cell = grid[y][x]
      if (!cell) {
        grid[y][x] = [p.x, p.y, k]
      } else {
        cell[0] = (cell[0] * cell[2] + p.x * k) / (cell[2] + k)
        cell[1] = (cell[1] * cell[2] + p.y * k) / (cell[2] + k)
        cell[2] += k
      }
    }

    for (let i = 0, len = grid.length; i < len; i++) {
      if (!grid[i]) continue
      for (let j = 0, len2 = grid[i].length; j < len2; j++) {
        const cell = grid[i][j]
        if (cell) data.push([Math.round(cell[0]), Math.round(cell[1]), Math.min(cell[2], max)])
      }
    }

    this._heat.data(data).draw(this.options.minOpacity)
    this._frame = null
  },
  _animateZoom(e) {
    const scale = this._map.getZoomScale(e.zoom)
    const offset = this._map
      ._getCenterOffset(e.center)
      ._multiplyBy(-scale)
      .subtract(this._map._getMapPanePos())
    if (L.DomUtil.setTransform) {
      L.DomUtil.setTransform(this._canvas, offset, scale)
    } else {
      this._canvas.style[L.DomUtil.TRANSFORM] =
        L.DomUtil.getTranslateString(offset) + ' scale(' + scale + ')'
    }
  },
})

export function createHeatLayer(latlngs, options) {
  return new HeatLayer(latlngs, options)
}
