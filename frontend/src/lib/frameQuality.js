// Frame quality gate for the live scanner.
//
// Why this exists: a phone pointed at a crop produces a stream of mostly
// unusable frames -- motion blur while the farmer moves, deep shade under the
// canopy, glare in direct sun. Running the model on those and reporting the
// result is how you get a confident wrong answer.
//
// So a frame is scored before it is allowed to influence the verdict, and the
// UI tells the farmer what to fix ("hold steady", "move into better light")
// rather than silently producing noise. This is the single biggest difference
// between a live scanner that works in a field and a demo that works on a desk.
//
// Thresholds are starting points from typical phone cameras and SHOULD be
// re-tuned against real field footage before deployment.

export const QUALITY_DEFAULTS = {
  minSharpness: 45, // variance of Laplacian; below this the lesion edges are mush
  minBrightness: 45, // 0-255 mean luma; below this is deep shade
  maxBrightness: 225, // above this is blown-out glare
  sampleSize: 96, // downscale before analysis -- this runs every frame
}

/**
 * Score one frame. `imageData` is RGBA from canvas.getImageData().
 * Returns { ok, sharpness, brightness, issues: [...] }.
 */
export function assessFrame(imageData, options = {}) {
  const cfg = { ...QUALITY_DEFAULTS, ...options }
  const { data, width, height } = imageData

  // Grayscale (Rec. 601 luma), which is what both metrics operate on.
  const gray = new Float32Array(width * height)
  let sum = 0
  for (let i = 0, p = 0; i < data.length; i += 4, p += 1) {
    const luma = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]
    gray[p] = luma
    sum += luma
  }
  const brightness = sum / gray.length

  // Variance of the Laplacian: the standard cheap focus metric. A sharp image
  // has strong second derivatives at edges; a blurred one does not.
  let lapSum = 0
  let lapSqSum = 0
  let count = 0
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const i = y * width + x
      const lap =
        4 * gray[i] - gray[i - 1] - gray[i + 1] - gray[i - width] - gray[i + width]
      lapSum += lap
      lapSqSum += lap * lap
      count += 1
    }
  }
  const mean = count ? lapSum / count : 0
  const sharpness = count ? lapSqSum / count - mean * mean : 0

  const issues = []
  if (brightness < cfg.minBrightness) issues.push('too_dark')
  else if (brightness > cfg.maxBrightness) issues.push('too_bright')
  if (sharpness < cfg.minSharpness) issues.push('too_blurry')

  return {
    ok: issues.length === 0,
    sharpness: Math.round(sharpness),
    brightness: Math.round(brightness),
    issues,
  }
}

/** Actionable guidance, not diagnostics -- the farmer has to know what to do. */
export const QUALITY_HINTS = {
  too_dark: {
    en: 'Too dark. Move into better light',
    mr: 'खूप अंधार. उजेडात या',
    hi: 'बहुत अंधेरा. बेहतर रोशनी में आएँ',
    bn: 'খুব অন্ধকার. ভালো আলোয় আসুন',
  },
  too_bright: {
    en: 'Too bright. Avoid direct glare',
    mr: 'खूप प्रखर प्रकाश. थेट उन्हात नको',
    hi: 'बहुत तेज़ रोशनी. सीधी चमक से बचें',
    bn: 'খুব উজ্জ্বল. সরাসরি ঝলকানি এড়ান',
  },
  too_blurry: {
    en: 'Image is blurred. Hold still',
    mr: 'चित्र अस्पष्ट आहे. स्थिर धरा',
    hi: 'तस्वीर धुंधली है. स्थिर रखें',
    bn: 'ছবি ঝাপসা. স্থির রাখুন',
  },
}

export const hintFor = (issue, lang = 'en') =>
  QUALITY_HINTS[issue]?.[lang] ?? QUALITY_HINTS[issue]?.en ?? issue
