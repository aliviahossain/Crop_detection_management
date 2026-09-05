import { useEffect, useRef } from 'react'
import { useMap } from 'react-leaflet'
import { createHeatLayer } from '../lib/heatLayer.js'

// Bridges the vendored Leaflet heat layer into react-leaflet. `points` is an
// array of [lat, lng, weight]; `options` are simpleheat options (radius, blur,
// max, gradient). The layer is created once and then fed new data/options.
export default function HeatmapLayer({ points, options }) {
  const map = useMap()
  const layerRef = useRef(null)

  useEffect(() => {
    const layer = createHeatLayer(points, options)
    layer.addTo(map)
    layerRef.current = layer
    return () => {
      map.removeLayer(layer)
      layerRef.current = null
    }
    // Created once for this map; data/options flow through the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map])

  useEffect(() => {
    if (layerRef.current) layerRef.current.setOptions(options || {})
  }, [options])

  useEffect(() => {
    if (layerRef.current) layerRef.current.setLatLngs(points || [])
  }, [points])

  return null
}
