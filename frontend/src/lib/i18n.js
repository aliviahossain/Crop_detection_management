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

  'nav.scan': {
    en: 'Live scan',
    mr: 'थेट स्कॅन',
    hi: 'लाइव स्कैन',
    bn: 'লাইভ স্ক্যান',
  },
  'scan.help': {
    en: 'Point your camera at the crop. Hold steady until the reading settles, then accept or discard it.',
    mr: 'कॅमेरा पिकाकडे धरा. वाचन स्थिर होईपर्यंत स्थिर धरा, नंतर स्वीकारा किंवा नाकारा.',
    hi: 'कैमरा फसल की ओर रखें। रीडिंग स्थिर होने तक स्थिर रखें, फिर स्वीकारें या अस्वीकारें।',
    bn: 'ক্যামেরা ফসলের দিকে ধরুন। রিডিং স্থির না হওয়া পর্যন্ত স্থির রাখুন, তারপর গ্রহণ বা বাতিল করুন।',
  },
  'scan.start': {
    en: 'Start camera',
    mr: 'कॅमेरा सुरू करा',
    hi: 'कैमरा शुरू करें',
    bn: 'ক্যামেরা চালু করুন',
  },
  'scan.stop': {
    en: 'Stop camera',
    mr: 'कॅमेरा बंद करा',
    hi: 'कैमरा बंद करें',
    bn: 'ক্যামেরা বন্ধ করুন',
  },
  'scan.pressStart': {
    en: 'Press Start camera to begin scanning',
    mr: 'स्कॅन सुरू करण्यासाठी कॅमेरा सुरू करा दाबा',
    hi: 'स्कैन शुरू करने के लिए कैमरा शुरू करें दबाएँ',
    bn: 'স্ক্যান শুরু করতে ক্যামেরা চালু করুন চাপুন',
  },
  'scan.denied': {
    en: 'Camera permission denied',
    mr: 'कॅमेरा परवानगी नाकारली',
    hi: 'कैमरा अनुमति अस्वीकृत',
    bn: 'ক্যামেরার অনুমতি দেওয়া হয়নি',
  },
  'scan.deniedHelp': {
    en: 'Allow camera access in your browser settings, then press Start again.',
    mr: 'ब्राउझर सेटिंग्जमध्ये कॅमेरा परवानगी द्या, नंतर पुन्हा सुरू करा दाबा.',
    hi: 'ब्राउज़र सेटिंग्स में कैमरा अनुमति दें, फिर से शुरू करें दबाएँ।',
    bn: 'ব্রাউজার সেটিংসে ক্যামেরার অনুমতি দিন, তারপর আবার চালু করুন চাপুন।',
  },
  'scan.holdSteady': {
    en: 'Hold steady',
    mr: 'स्थिर धरा',
    hi: 'स्थिर रखें',
    bn: 'স্থির রাখুন',
  },
  'scan.settling': {
    en: 'Reading is settling…',
    mr: 'वाचन स्थिर होत आहे…',
    hi: 'रीडिंग स्थिर हो रही है…',
    bn: 'রিডিং স্থির হচ্ছে…',
  },
  'scan.verdict': {
    en: 'Verdict',
    mr: 'निष्कर्ष',
    hi: 'निष्कर्ष',
    bn: 'ফলাফল',
  },
  'scan.accept': {
    en: 'Accept',
    mr: 'स्वीकारा',
    hi: 'स्वीकारें',
    bn: 'গ্রহণ করুন',
  },
  'scan.discard': {
    en: 'Discard',
    mr: 'नाकारा',
    hi: 'अस्वीकारें',
    bn: 'বাতিল করুন',
  },
  'scan.accepted': {
    en: 'Scan accepted and recorded',
    mr: 'स्कॅन स्वीकारले व नोंदवले',
    hi: 'स्कैन स्वीकृत और दर्ज',
    bn: 'স্ক্যান গৃহীত ও নথিভুক্ত',
  },
  'scan.scanAgain': {
    en: 'Scan another plant',
    mr: 'दुसरे झाड स्कॅन करा',
    hi: 'दूसरा पौधा स्कैन करें',
    bn: 'আরেকটি গাছ স্ক্যান করুন',
  },
  'scan.acceptExplain': {
    en: 'Accepting saves this frame as a case with a full advisory. Discarding keeps scanning and stores nothing.',
    mr: 'स्वीकारल्यास ही फ्रेम संपूर्ण सल्ल्यासह प्रकरण म्हणून जतन होते. नाकारल्यास काहीही साठवले जात नाही.',
    hi: 'स्वीकारने पर यह फ्रेम पूरी सलाह के साथ केस के रूप में सहेजा जाता है। अस्वीकारने पर कुछ भी संग्रहित नहीं होता।',
    bn: 'গ্রহণ করলে এই ফ্রেম সম্পূর্ণ পরামর্শসহ কেস হিসেবে সংরক্ষিত হয়। বাতিল করলে কিছুই সংরক্ষিত হয় না।',
  },
  'scan.agreement': {
    en: 'Agreement',
    mr: 'सहमती',
    hi: 'सहमति',
    bn: 'সঙ্গতি',
  },
  'scan.frames': {
    en: 'frames',
    mr: 'फ्रेम',
    hi: 'फ़्रेम',
    bn: 'ফ্রেম',
  },
  'scan.noDetection': {
    en: 'Nothing recognised',
    mr: 'काहीही ओळखले नाही',
    hi: 'कुछ पहचाना नहीं गया',
    bn: 'কিছু শনাক্ত হয়নি',
  },
  'scan.noDetectionHelp': {
    en: 'The model recognises nothing here. Move closer to an affected leaf, or the problem may be outside the three potato classes it knows.',
    mr: 'येथे मॉडेलला काहीही ओळखता आले नाही. रोगग्रस्त पानाजवळ जा, किंवा समस्या त्याला माहीत असलेल्या तीन वर्गांबाहेरची असू शकते.',
    hi: 'मॉडल यहाँ कुछ नहीं पहचानता। प्रभावित पत्ती के पास जाएँ, या समस्या उसके तीन ज्ञात वर्गों से बाहर हो सकती है।',
    bn: 'মডেল এখানে কিছু চিনতে পারছে না। আক্রান্ত পাতার কাছে যান, অথবা সমস্যাটি তার জানা তিনটি শ্রেণির বাইরে হতে পারে।',
  },
  'scan.scanningHelp': {
    en: 'Collecting frames. Keep the leaf filling the frame and hold still.',
    mr: 'फ्रेम गोळा करत आहे. पान चौकटीत भरलेले ठेवा आणि स्थिर धरा.',
    hi: 'फ़्रेम एकत्र कर रहे हैं। पत्ती को फ्रेम में भरा रखें और स्थिर रहें।',
    bn: 'ফ্রেম সংগ্রহ করা হচ্ছে। পাতা ফ্রেম জুড়ে রাখুন এবং স্থির থাকুন।',
  },
  'scan.unstableHelp': {
    en: 'The readings disagree with each other, so no verdict is offered yet. Move slightly closer and hold still.',
    mr: 'वाचनांमध्ये एकवाक्यता नाही, त्यामुळे अद्याप निष्कर्ष दिला जात नाही. थोडे जवळ जा आणि स्थिर धरा.',
    hi: 'रीडिंग आपस में मेल नहीं खा रहीं, इसलिए अभी निष्कर्ष नहीं दिया गया। थोड़ा पास जाएँ और स्थिर रहें।',
    bn: 'রিডিংগুলো একে অপরের সাথে মিলছে না, তাই এখনও ফলাফল দেওয়া হয়নি। একটু কাছে যান এবং স্থির থাকুন।',
  },
  'scan.qualityWait': {
    en: 'The image is not clear enough to judge. Fix the lighting or hold steadier.',
    mr: 'निर्णय घेण्याइतके चित्र स्पष्ट नाही. प्रकाश सुधारा किंवा अधिक स्थिर धरा.',
    hi: 'निर्णय लेने के लिए तस्वीर पर्याप्त स्पष्ट नहीं है। रोशनी ठीक करें या अधिक स्थिर रखें।',
    bn: 'সিদ্ধান্ত নেওয়ার মতো ছবি যথেষ্ট স্পষ্ট নয়। আলো ঠিক করুন বা আরও স্থির রাখুন।',
  },
  'scan.onDevice': {
    en: 'On-device · offline capable',
    mr: 'डिव्हाइसवर · ऑफलाइन चालते',
    hi: 'डिवाइस पर · ऑफ़लाइन सक्षम',
    bn: 'ডিভাইসে · অফলাইনে চলে',
  },
  'scan.serverMode': {
    en: 'Server inference',
    mr: 'सर्व्हरवर विश्लेषण',
    hi: 'सर्वर पर विश्लेषण',
    bn: 'সার্ভারে বিশ্লেষণ',
  },
  'scan.noModel': {
    en: 'No detection model is installed, so live scanning is unavailable.',
    mr: 'शोध मॉडेल स्थापित नाही, त्यामुळे थेट स्कॅन उपलब्ध नाही.',
    hi: 'कोई डिटेक्शन मॉडल स्थापित नहीं है, इसलिए लाइव स्कैन उपलब्ध नहीं है।',
    bn: 'কোনো শনাক্তকরণ মডেল ইনস্টল করা নেই, তাই লাইভ স্ক্যান পাওয়া যাচ্ছে না।',
  },
  'scan.howItWorks': {
    en: 'How this works',
    mr: 'हे कसे चालते',
    hi: 'यह कैसे काम करता है',
    bn: 'এটি কীভাবে কাজ করে',
  },
  'scan.how1': {
    en: 'Blurred or badly lit frames are rejected before the model sees them.',
    mr: 'अस्पष्ट किंवा कमी प्रकाशातील फ्रेम मॉडेलपर्यंत पोहोचण्यापूर्वीच नाकारल्या जातात.',
    hi: 'धुंधले या कम रोशनी वाले फ़्रेम मॉडल तक पहुँचने से पहले ही अस्वीकृत हो जाते हैं।',
    bn: 'ঝাপসা বা কম আলোর ফ্রেম মডেলে পৌঁছানোর আগেই বাতিল হয়।',
  },
  'scan.how2': {
    en: 'A verdict appears only after several frames agree, never from one lucky frame.',
    mr: 'अनेक फ्रेम एकमत झाल्यावरच निष्कर्ष दिसतो, एका फ्रेमवरून कधीही नाही.',
    hi: 'निष्कर्ष तभी दिखता है जब कई फ़्रेम सहमत हों, किसी एक फ़्रेम से कभी नहीं।',
    bn: 'একাধিক ফ্রেম একমত হলেই কেবল ফলাফল দেখায়, একটি ফ্রেম থেকে কখনও নয়।',
  },
  'scan.how3': {
    en: 'Nothing is saved until you press Accept. Discarded scans leave no record.',
    mr: 'स्वीकारा दाबेपर्यंत काहीही जतन होत नाही. नाकारलेल्या स्कॅनची नोंद राहत नाही.',
    hi: 'स्वीकारें दबाने तक कुछ भी सहेजा नहीं जाता। अस्वीकृत स्कैन का कोई रिकॉर्ड नहीं रहता।',
    bn: 'গ্রহণ করুন চাপার আগে কিছুই সংরক্ষিত হয় না। বাতিল করা স্ক্যানের কোনো রেকর্ড থাকে না।',
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
