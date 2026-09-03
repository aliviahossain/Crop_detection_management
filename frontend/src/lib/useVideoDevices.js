import { useCallback, useEffect, useState } from 'react'

/** Lists the available video input cameras (e.g. a laptop's built-in webcam and
 *  a phone connected as a camera). Device labels are only populated once camera
 *  permission has been granted, so `refresh` is exposed to re-read them right
 *  after a successful getUserMedia call. */
export function useVideoDevices() {
  const [devices, setDevices] = useState([])

  const refresh = useCallback(async () => {
    try {
      const all = await navigator.mediaDevices.enumerateDevices()
      setDevices(all.filter((d) => d.kind === 'videoinput'))
    } catch {
      /* enumeration can fail before permission; ignore */
    }
  }, [])

  useEffect(() => {
    refresh()
    navigator.mediaDevices?.addEventListener?.('devicechange', refresh)
    return () => navigator.mediaDevices?.removeEventListener?.('devicechange', refresh)
  }, [refresh])

  return { devices, refresh }
}
