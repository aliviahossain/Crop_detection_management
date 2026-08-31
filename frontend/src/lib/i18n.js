// UI chrome translations. The *advisory content* is translated server-side by
// the message catalog in backend/app/services/translate.py -- this file only
// covers labels, buttons and headings, so the two never disagree about a dose.
import { createContext, useContext } from 'react'

export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'mr', label: 'मराठी' },
  { code: 'hi', label: 'हिन्दी' },
  { code: 'bn', label: 'বাংলা' },
]

const STRINGS = {
  'app.title': {
    en: 'CropGuard',
    mr: 'क्रॉपगार्ड',
    hi: 'क्रॉपगार्ड',
    bn: 'ক্রপগার্ড',
  },
  'app.subtitle': {
    en: 'Potato disease & pest early warning',
    mr: 'बटाटा रोग व कीड पूर्वसूचना',
    hi: 'आलू रोग एवं कीट पूर्व चेतावनी',
    bn: 'আলুর রোগ ও পোকার আগাম সতর্কতা',
  },

  'nav.check': {
    en: 'Check crop',
    mr: 'पीक तपासा',
    hi: 'फसल जाँचें',
    bn: 'ফসল পরীক্ষা করুন',
  },
  'nav.risk': {
    en: 'Risk forecast',
    mr: 'धोका अंदाज',
    hi: 'जोखिम पूर्वानुमान',
    bn: 'ঝুঁকির পূর্বাভাস',
  },
  'nav.map': {
    en: 'Hotspot map',
    mr: 'हॉटस्पॉट नकाशा',
    hi: 'हॉटस्पॉट मानचित्र',
    bn: 'হটস্পট মানচিত্র',
  },
  'nav.dashboard': {
    en: 'Dashboard',
    mr: 'डॅशबोर्ड',
    hi: 'डैशबोर्ड',
    bn: 'ড্যাশবোর্ড',
  },
  'nav.review': {
    en: 'Expert review',
    mr: 'तज्ज्ञ तपासणी',
    hi: 'विशेषज्ञ समीक्षा',
    bn: 'বিশেষজ্ঞ পর্যালোচনা',
  },

  'farmer.heading': {
    en: 'Photograph your crop',
    mr: 'आपल्या पिकाचा फोटो काढा',
    hi: 'अपनी फसल की तस्वीर लें',
    bn: 'আপনার ফসলের ছবি তুলুন',
  },
  'farmer.help': {
    en: 'Take a close photo of the affected leaf in daylight, filling the frame.',
    mr: 'दिवसाच्या प्रकाशात रोगग्रस्त पानाचा जवळून, पूर्ण चौकटीत फोटो घ्या.',
    hi: 'दिन के उजाले में प्रभावित पत्ती की नज़दीकी, पूरी फ्रेम की तस्वीर लें।',
    bn: 'দিনের আলোয় আক্রান্ত পাতার কাছ থেকে, পুরো ফ্রেম জুড়ে ছবি তুলুন।',
  },
  'farmer.choose': {
    en: 'Choose photo',
    mr: 'फोटो निवडा',
    hi: 'तस्वीर चुनें',
    bn: 'ছবি নির্বাচন করুন',
  },
  'farmer.submit': {
    en: 'Get diagnosis',
    mr: 'निदान मिळवा',
    hi: 'निदान प्राप्त करें',
    bn: 'রোগ নির্ণয় করুন',
  },
  'farmer.analysing': {
    en: 'Analysing…',
    mr: 'तपासत आहे…',
    hi: 'जाँच हो रही है…',
    bn: 'পরীক্ষা করা হচ্ছে…',
  },

  'field.location': {
    en: 'Location',
    mr: 'स्थान',
    hi: 'स्थान',
    bn: 'অবস্থান',
  },
  'field.district': {
    en: 'District',
    mr: 'जिल्हा',
    hi: 'ज़िला',
    bn: 'জেলা',
  },
  'field.village': {
    en: 'Village',
    mr: 'गाव',
    hi: 'गाँव',
    bn: 'গ্রাম',
  },
  'field.variety': {
    en: 'Variety',
    mr: 'वाण',
    hi: 'किस्म',
    bn: 'জাত',
  },
  'field.stage': {
    en: 'Crop stage',
    mr: 'पिकाची अवस्था',
    hi: 'फसल अवस्था',
    bn: 'ফসলের অবস্থা',
  },
  'field.soil': {
    en: 'Soil condition',
    mr: 'जमिनीची स्थिती',
    hi: 'मिट्टी की स्थिति',
    bn: 'মাটির অবস্থা',
  },
  'field.name': {
    en: 'Your name',
    mr: 'आपले नाव',
    hi: 'आपका नाम',
    bn: 'আপনার নাম',
  },
  'field.phone': {
    en: 'Phone',
    mr: 'मोबाइल',
    hi: 'मोबाइल',
    bn: 'মোবাইল',
  },
  'field.severity': {
    en: 'Share of field affected',
    mr: 'बाधित शेताचा भाग',
    hi: 'प्रभावित खेत का हिस्सा',
    bn: 'আক্রান্ত জমির অংশ',
  },
  'field.locate': {
    en: 'Use my location',
    mr: 'माझे स्थान वापरा',
    hi: 'मेरा स्थान उपयोग करें',
    bn: 'আমার অবস্থান ব্যবহার করুন',
  },

  'risk.heading': {
    en: 'Weather-based risk forecast',
    mr: 'हवामान आधारित धोका अंदाज',
    hi: 'मौसम आधारित जोखिम पूर्वानुमान',
    bn: 'আবহাওয়া ভিত্তিক ঝুঁকির পূর্বাভাস',
  },
  'risk.explain': {
    en: 'Predicts risk before symptoms appear, using published agronomic models.',
    mr: 'लक्षणे दिसण्यापूर्वीच, प्रस्थापित कृषिशास्त्रीय प्रारूपांद्वारे धोका वर्तवते.',
    hi: 'लक्षण दिखने से पहले, स्थापित कृषि-वैज्ञानिक मॉडलों से जोखिम बताता है।',
    bn: 'প্রতিষ্ঠিত কৃষিবিজ্ঞান মডেল ব্যবহার করে লক্ষণ দেখা দেওয়ার আগেই ঝুঁকি জানায়।',
  },
  'risk.check': {
    en: 'Check risk',
    mr: 'धोका तपासा',
    hi: 'जोखिम जाँचें',
    bn: 'ঝুঁকি পরীক্ষা করুন',
  },
  'risk.evidence': {
    en: 'Why this level?',
    mr: 'ही पातळी का?',
    hi: 'यह स्तर क्यों?',
    bn: 'এই মাত্রা কেন?',
  },

  'result.diagnosis': {
    en: 'Diagnosis',
    mr: 'निदान',
    hi: 'निदान',
    bn: 'রোগ নির্ণয়',
  },
  'result.confidence': {
    en: 'Confidence',
    mr: 'खात्री',
    hi: 'विश्वास',
    bn: 'নিশ্চয়তা',
  },
  'result.escalated': {
    en: 'Expert confirmation needed',
    mr: 'तज्ज्ञांची खात्री आवश्यक',
    hi: 'विशेषज्ञ पुष्टि आवश्यक',
    bn: 'বিশেষজ্ঞের নিশ্চিতকরণ প্রয়োজন',
  },
  'result.newCheck': {
    en: 'Check another photo',
    mr: 'दुसरा फोटो तपासा',
    hi: 'दूसरी तस्वीर जाँचें',
    bn: 'আরেকটি ছবি পরীক্ষা করুন',
  },

  'common.loading': {
    en: 'Loading…',
    mr: 'लोड होत आहे…',
    hi: 'लोड हो रहा है…',
    bn: 'লোড হচ্ছে…',
  },
  'common.error': {
    en: 'Something went wrong',
    mr: 'काहीतरी चूक झाली',
    hi: 'कुछ गड़बड़ हुई',
    bn: 'কিছু একটা ভুল হয়েছে',
  },
  'common.optional': {
    en: 'optional',
    mr: 'ऐच्छिक',
    hi: 'वैकल्पिक',
    bn: 'ঐচ্ছিক',
  },
  'common.none': {
    en: 'No data yet',
    mr: 'अद्याप माहिती नाही',
    hi: 'अभी कोई डेटा नहीं',
    bn: 'এখনও কোনো তথ্য নেই',
  },
}

export const LangContext = createContext({ lang: 'en', setLang: () => {} })

export function useLang() {
  return useContext(LangContext)
}

export function useT() {
  const { lang } = useLang()
  return (key) => STRINGS[key]?.[lang] ?? STRINGS[key]?.en ?? key
}

// Exported so a test (or a dev) can check no language has silently fallen behind.
export const translationCoverage = () =>
  Object.fromEntries(
    LANGUAGES.map(({ code }) => {
      const total = Object.keys(STRINGS).length
      const have = Object.values(STRINGS).filter((entry) => entry[code]).length
      return [code, { have, total, coverage: have / total }]
    }),
  )

export const STAGE_OPTIONS = [
  'sowing',
  'emergence',
  'vegetative',
  'tuber_initiation',
  'tuber_bulking',
  'maturity',
  'harvest',
]
export const SOIL_OPTIONS = ['well_drained', 'normal', 'poorly_drained', 'waterlogged', 'sandy', 'clay']
export const VARIETY_OPTIONS = [
  'Kufri Jyoti',
  'Kufri Pukhraj',
  'Kufri Badshah',
  'Kufri Chandramukhi',
  'Kufri Himalini',
  'Kufri Girdhari',
  'Kufri Chipsona-1',
]

export const prettify = (value) =>
  (value || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
