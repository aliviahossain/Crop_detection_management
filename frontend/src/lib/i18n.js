// UI chrome translations. Advisory *content* is translated server-side by
// backend/app/services/translate.py, so the two never disagree about a dose.
import { createContext, useContext } from 'react'

export const LANGUAGES = [
  { code: 'mr', label: 'मराठी', sub: 'Marathi' },
  { code: 'hi', label: 'हिन्दी', sub: 'Hindi' },
  { code: 'bn', label: 'বাংলা', sub: 'Bengali' },
  { code: 'en', label: 'English', sub: 'English' },
]

const STRINGS = {
  'app.title': { en: 'CropGuard', mr: 'क्रॉपगार्ड', hi: 'क्रॉपगार्ड', bn: 'ক্রপগার্ড' },
  'app.subtitle': {
    en: 'Potato disease alerts',
    mr: 'बटाटा रोग इशारे',
    hi: 'आलू रोग चेतावनी',
    bn: 'আলুর রোগ সতর্কতা',
  },

  'menu.open': { en: 'Menu', mr: 'मेनू', hi: 'मेनू', bn: 'মেনু' },
  'menu.close': { en: 'Close', mr: 'बंद करा', hi: 'बंद करें', bn: 'বন্ধ করুন' },
  'menu.language': { en: 'Language', mr: 'भाषा', hi: 'भाषा', bn: 'ভাষা' },
  'menu.farmer': { en: 'For farmers', mr: 'शेतकऱ्यांसाठी', hi: 'किसानों के लिए', bn: 'কৃষকদের জন্য' },
  'menu.officer': { en: 'For officers', mr: 'अधिकाऱ्यांसाठी', hi: 'अधिकारियों के लिए', bn: 'কর্মকর্তাদের জন্য' },

  'nav.home': { en: 'Today', mr: 'आज', hi: 'आज', bn: 'আজ' },
  'nav.home.desc': {
    en: 'Your daily alert',
    mr: 'तुमचा रोजचा इशारा',
    hi: 'आपकी रोज़ की चेतावनी',
    bn: 'আপনার দৈনিক সতর্কতা',
  },
  'nav.check': { en: 'Check crop', mr: 'पीक तपासा', hi: 'फसल जाँचें', bn: 'ফসল দেখুন' },
  'nav.check.desc': {
    en: 'Photo to diagnosis',
    mr: 'फोटोवरून निदान',
    hi: 'फोटो से निदान',
    bn: 'ছবি থেকে রোগ',
  },
  'nav.scan': { en: 'Live scan', mr: 'थेट स्कॅन', hi: 'लाइव स्कैन', bn: 'লাইভ স্ক্যান' },
  'nav.scan.desc': {
    en: 'Camera, instant result',
    mr: 'कॅमेरा, लगेच निकाल',
    hi: 'कैमरा, तुरंत नतीजा',
    bn: 'ক্যামেরা, সাথে সাথে ফল',
  },
  'nav.risk': { en: 'Risk forecast', mr: 'धोका अंदाज', hi: 'जोखिम अनुमान', bn: 'ঝুঁকির পূর্বাভাস' },
  'nav.risk.desc': {
    en: 'Warning before symptoms',
    mr: 'लक्षणांआधी इशारा',
    hi: 'लक्षण से पहले चेतावनी',
    bn: 'লক্ষণের আগে সতর্কতা',
  },
  'nav.map': { en: 'Hotspot map', mr: 'हॉटस्पॉट नकाशा', hi: 'हॉटस्पॉट नक्शा', bn: 'হটস্পট মানচিত্র' },
  'nav.map.desc': {
    en: 'Where cases cluster',
    mr: 'प्रकरणे कुठे आहेत',
    hi: 'मामले कहाँ हैं',
    bn: 'কোথায় বেশি',
  },
  'nav.dashboard': { en: 'Dashboard', mr: 'डॅशबोर्ड', hi: 'डैशबोर्ड', bn: 'ড্যাশবোর্ড' },
  'nav.dashboard.desc': {
    en: 'Numbers and trends',
    mr: 'आकडे व कल',
    hi: 'आँकड़े और रुझान',
    bn: 'সংখ্যা ও প্রবণতা',
  },
  'nav.review': { en: 'Expert review', mr: 'तज्ज्ञ तपासणी', hi: 'विशेषज्ञ जाँच', bn: 'বিশেষজ্ঞ যাচাই' },
  'nav.review.desc': {
    en: 'Confirm AI diagnoses',
    mr: 'निदान पडताळा',
    hi: 'निदान की पुष्टि',
    bn: 'রোগ নির্ণয় যাচাই',
  },

  'farmer.heading': {
    en: 'Photograph your crop',
    mr: 'पिकाचा फोटो काढा',
    hi: 'फसल की फोटो लें',
    bn: 'ফসলের ছবি তুলুন',
  },
  'farmer.help': {
    en: 'One close photo of the sick leaf, in daylight.',
    mr: 'रोगट पानाचा एक जवळचा फोटो, दिवसाच्या उजेडात.',
    hi: 'बीमार पत्ती की एक नज़दीकी फोटो, दिन के उजाले में.',
    bn: 'অসুস্থ পাতার একটি কাছের ছবি, দিনের আলোয়.',
  },
  'farmer.choose': { en: 'Choose photo', mr: 'फोटो निवडा', hi: 'फोटो चुनें', bn: 'ছবি বাছুন' },
  'farmer.takePhoto': { en: 'Take photo', mr: 'फोटो काढा', hi: 'फोटो लें', bn: 'ছবি তুলুন' },
  'farmer.upload': { en: 'Upload photo', mr: 'फोटो अपलोड करा', hi: 'फोटो अपलोड करें', bn: 'ছবি আপলোড করুন' },
  'farmer.capture': { en: 'Capture', mr: 'टिपा', hi: 'खींचें', bn: 'তুলুন' },

  'farmer.tapPhoto': {
    en: 'Tap to take or pick a photo',
    mr: 'फोटो काढण्यासाठी किंवा निवडण्यासाठी दाबा',
    hi: 'फोटो लेने या चुनने के लिए दबाएँ',
    bn: 'ছবি তুলতে বা বাছতে চাপুন',
  },
  'farmer.submit': { en: 'Get diagnosis', mr: 'निदान मिळवा', hi: 'निदान पाएँ', bn: 'রোগ জানুন' },
  'farmer.analysing': { en: 'Checking', mr: 'तपासत आहे', hi: 'जाँच रहे हैं', bn: 'দেখা হচ্ছে' },
  'farmer.waiting': {
    en: 'Add a photo. You get the disease name, what to do, and the weather risk for your field.',
    mr: 'फोटो जोडा. रोगाचे नाव, काय करावे आणि शेतासाठी हवामान धोका मिळेल.',
    hi: 'फोटो जोड़ें. रोग का नाम, क्या करें और खेत का मौसम जोखिम मिलेगा.',
    bn: 'ছবি দিন. রোগের নাম, কী করবেন আর জমির আবহাওয়া ঝুঁকি পাবেন.',
  },
  'farmer.details': { en: 'Field details', mr: 'शेताची माहिती', hi: 'खेत की जानकारी', bn: 'জমির তথ্য' },
  'farmer.detailsHelp': {
    en: 'Optional, but a filled form gives a sharper risk score.',
    mr: 'ऐच्छिक, पण भरल्यास धोका अधिक अचूक मिळतो.',
    hi: 'वैकल्पिक, पर भरने से जोखिम ज़्यादा सटीक मिलता है.',
    bn: 'ঐচ্ছিক, তবে দিলে ঝুঁকি আরও নিখুঁত হয়.',
  },
  'farmer.noModel': {
    en: 'No detector is installed here, so nothing was guessed. An expert will look at this case.',
    mr: 'येथे शोध मॉडेल नाही, त्यामुळे अंदाज लावला नाही. तज्ज्ञ हे प्रकरण पाहतील.',
    hi: 'यहाँ कोई मॉडल नहीं है, इसलिए अंदाज़ा नहीं लगाया. विशेषज्ञ इसे देखेंगे.',
    bn: 'এখানে মডেল নেই, তাই অনুমান করা হয়নি. বিশেষজ্ঞ এটি দেখবেন.',
  },
  'farmer.saved': {
    en: 'Saved as case #{id}. An officer can see it now.',
    mr: 'प्रकरण #{id} म्हणून जतन. अधिकारी ते आता पाहू शकतात.',
    hi: 'केस #{id} के रूप में सहेजा. अधिकारी इसे अब देख सकते हैं.',
    bn: 'কেস #{id} হিসেবে সংরক্ষিত. কর্মকর্তা এখন দেখতে পাবেন.',
  },

  'field.location': { en: 'Location', mr: 'स्थान', hi: 'स्थान', bn: 'অবস্থান' },
  'field.district': { en: 'District', mr: 'जिल्हा', hi: 'ज़िला', bn: 'জেলা' },
  'field.village': { en: 'Village', mr: 'गाव', hi: 'गाँव', bn: 'গ্রাম' },
  'field.variety': { en: 'Variety', mr: 'वाण', hi: 'किस्म', bn: 'জাত' },
  'field.stage': { en: 'Crop stage', mr: 'पिकाची अवस्था', hi: 'फसल अवस्था', bn: 'ফসলের অবস্থা' },
  'field.soil': { en: 'Soil', mr: 'जमीन', hi: 'मिट्टी', bn: 'মাটি' },
  'field.name': { en: 'Your name', mr: 'आपले नाव', hi: 'आपका नाम', bn: 'আপনার নাম' },
  'field.phone': { en: 'Phone', mr: 'मोबाइल', hi: 'मोबाइल', bn: 'মোবাইল' },
  'field.severity': {
    en: 'Field affected',
    mr: 'बाधित शेत',
    hi: 'प्रभावित खेत',
    bn: 'আক্রান্ত জমি',
  },
  'field.locate': { en: 'Use my location', mr: 'माझे स्थान वापरा', hi: 'मेरा स्थान लें', bn: 'আমার অবস্থান নিন' },
  'field.locating': { en: 'Finding you', mr: 'शोधत आहे', hi: 'खोज रहे हैं', bn: 'খোঁজা হচ্ছে' },
  'field.locateFailed': {
    en: 'Could not get your location. Type it in.',
    mr: 'स्थान मिळाले नाही. हाताने भरा.',
    hi: 'स्थान नहीं मिला. हाथ से भरें.',
    bn: 'অবস্থান পাওয়া যায়নি. হাতে লিখুন.',
  },

  'risk.heading': {
    en: 'Weather risk',
    mr: 'हवामान धोका',
    hi: 'मौसम जोखिम',
    bn: 'আবহাওয়া ঝুঁকি',
  },
  'risk.explain': {
    en: 'Warns you before symptoms show, from your local weather.',
    mr: 'स्थानिक हवामानावरून लक्षणे दिसण्याआधीच इशारा देते.',
    hi: 'स्थानीय मौसम से लक्षण दिखने से पहले चेतावनी देता है.',
    bn: 'স্থানীয় আবহাওয়া থেকে লক্ষণের আগেই সতর্ক করে.',
  },
  'risk.check': { en: 'Check risk', mr: 'धोका तपासा', hi: 'जोखिम जाँचें', bn: 'ঝুঁকি দেখুন' },
  'risk.needCoords': {
    en: 'Location is needed. Tap Use my location.',
    mr: 'स्थान हवे. माझे स्थान वापरा दाबा.',
    hi: 'स्थान चाहिए. मेरा स्थान लें दबाएँ.',
    bn: 'অবস্থান দরকার. আমার অবস্থান নিন চাপুন.',
  },
  'risk.saveCase': {
    en: 'Send this to the officer dashboard',
    mr: 'हे अधिकारी डॅशबोर्डवर पाठवा',
    hi: 'इसे अधिकारी डैशबोर्ड पर भेजें',
    bn: 'এটি কর্মকর্তার ড্যাশবোর্ডে পাঠান',
  },
  'risk.how': { en: 'How this works', mr: 'हे कसे चालते', hi: 'यह कैसे काम करता है', bn: 'এটি কীভাবে কাজ করে' },
  'risk.howText': {
    en: 'Published disease models read your weather, then adjust for crop stage, variety, soil and nearby confirmed cases. No photo needed.',
    mr: 'प्रस्थापित रोग प्रारूपे तुमचे हवामान वाचतात, मग पिकाची अवस्था, वाण, जमीन व जवळची प्रकरणे यानुसार जुळवतात. फोटो लागत नाही.',
    hi: 'स्थापित रोग मॉडल आपका मौसम पढ़ते हैं, फिर फसल अवस्था, किस्म, मिट्टी और आसपास के मामलों से मिलाते हैं. फोटो नहीं चाहिए.',
    bn: 'প্রতিষ্ঠিত রোগ মডেল আপনার আবহাওয়া পড়ে, তারপর ফসলের অবস্থা, জাত, মাটি ও কাছের কেস মিলিয়ে নেয়. ছবি লাগে না.',
  },

  'home.heading': {
    en: 'Today on your farm',
    mr: 'आज तुमच्या शेतात',
    hi: 'आज आपके खेत में',
    bn: 'আজ আপনার জমিতে',
  },
  'home.help': {
    en: 'One glance tells you if you should walk your field today.',
    mr: 'एका नजरेत कळते की आज शेत फिरायचे का.',
    hi: 'एक नज़र में पता चले कि आज खेत देखना है या नहीं.',
    bn: 'এক নজরেই বুঝুন আজ জমি ঘুরে দেখা দরকার কিনা.',
  },
  'home.status.calm.title': {
    en: 'All clear today',
    mr: 'आज सर्व ठीक',
    hi: 'आज सब ठीक',
    bn: 'আজ সব ঠিক',
  },
  'home.status.watch.title': {
    en: 'Keep an eye out',
    mr: 'लक्ष ठेवा',
    hi: 'नज़र रखें',
    bn: 'লক্ষ রাখুন',
  },
  'home.status.act.title': {
    en: 'Check your plants today',
    mr: 'आज झाडे तपासा',
    hi: 'आज पौधे जाँचें',
    bn: 'আজ গাছ দেখুন',
  },
  'home.reason.weather.act': {
    en: 'The weather is right for late blight to start.',
    mr: 'उशिरा करपा सुरू होण्यास हवामान अनुकूल आहे.',
    hi: 'पछेती झुलसा शुरू होने के लिए मौसम अनुकूल है.',
    bn: 'লেট ব্লাইট শুরু হওয়ার মতো আবহাওয়া.',
  },
  'home.reason.weather.watch': {
    en: 'Blight weather is building up.',
    mr: 'करपा हवामान वाढत आहे.',
    hi: 'झुलसा वाला मौसम बन रहा है.',
    bn: 'ব্লাইটের আবহাওয়া বাড়ছে.',
  },
  'home.reason.nearby.act': {
    en: 'Late blight is confirmed close to your field.',
    mr: 'तुमच्या शेताजवळ उशिरा करपा पक्का झाला आहे.',
    hi: 'आपके खेत के पास पछेती झुलसा पक्का हुआ है.',
    bn: 'আপনার জমির কাছে লেট ব্লাইট নিশ্চিত হয়েছে.',
  },
  'home.reason.nearby.watch': {
    en: 'A case was reported near you.',
    mr: 'तुमच्याजवळ एक प्रकरण नोंदवले गेले.',
    hi: 'आपके पास एक मामला दर्ज हुआ.',
    bn: 'আপনার কাছে একটি কেস জানানো হয়েছে.',
  },
  'home.reason.calm': {
    en: 'No blight weather and no cases nearby.',
    mr: 'करपा हवामान नाही आणि जवळ प्रकरणे नाहीत.',
    hi: 'न झुलसा मौसम, न पास कोई मामला.',
    bn: 'ব্লাইটের আবহাওয়াও নেই, কাছে কেসও নেই.',
  },
  'home.timeHint.morning': {
    en: 'Photograph your plants this morning, while dew is still on the leaf.',
    mr: 'पानावर दव असतानाच आज सकाळी झाडांचा फोटो काढा.',
    hi: 'पत्ती पर ओस रहते ही आज सुबह पौधों की फोटो लें.',
    bn: 'পাতায় শিশির থাকতেই আজ সকালে গাছের ছবি তুলুন.',
  },
  'home.action.photo': {
    en: 'Photograph a plant now',
    mr: 'आता झाडाचा फोटो काढा',
    hi: 'अभी पौधे की फोटो लें',
    bn: 'এখনই গাছের ছবি তুলুন',
  },
  'home.action.watch': {
    en: 'Learn what to look for',
    mr: 'काय पहावे ते जाणा',
    hi: 'क्या देखें, जानें',
    bn: 'কী দেখবেন জানুন',
  },
  'home.nearby.title': {
    en: 'Outbreaks near you',
    mr: 'तुमच्याजवळचा प्रादुर्भाव',
    hi: 'आपके पास फैलाव',
    bn: 'আপনার কাছে প্রাদুর্ভাব',
  },
  'home.nearby.confirmed': {
    en: '{n} confirmed within {km} km',
    mr: '{km} कि.मी. मध्ये {n} पक्के',
    hi: '{km} कि.मी. में {n} पक्के',
    bn: '{km} কিমির মধ্যে {n}টি নিশ্চিত',
  },
  'home.nearby.nearest': {
    en: 'nearest {km} km away',
    mr: 'सर्वात जवळचे {km} कि.मी.',
    hi: 'सबसे पास {km} कि.मी.',
    bn: 'সবচেয়ে কাছে {km} কিমি',
  },
  'home.nearby.reported': {
    en: '{n} unconfirmed report(s) nearby, awaiting an expert check.',
    mr: 'जवळ {n} अपुष्ट नोंद, तज्ज्ञ तपासणीच्या प्रतीक्षेत.',
    hi: 'पास {n} अपुष्ट रिपोर्ट, विशेषज्ञ जाँच बाकी.',
    bn: 'কাছে {n}টি অনিশ্চিত রিপোর্ট, বিশেষজ্ঞ যাচাই বাকি.',
  },
  'home.prevalent.title': {
    en: 'Most common in your area',
    mr: 'तुमच्या भागात सर्वाधिक',
    hi: 'आपके क्षेत्र में सबसे आम',
    bn: 'আপনার এলাকায় সবচেয়ে বেশি',
  },
  'home.prevalent.line': {
    en: '{disease}: {n} cases within {km} km',
    mr: '{disease}: {km} कि.मी.मध्ये {n} प्रकरणे',
    hi: '{disease}: {km} कि.मी. में {n} मामले',
    bn: '{disease}: {km} কিমির মধ্যে {n}টি কেস',
  },
  'home.prevalent.none': {
    en: 'No disease cases recorded in your area yet.',
    mr: 'तुमच्या भागात अद्याप रोग प्रकरणे नाहीत.',
    hi: 'आपके क्षेत्र में अभी कोई रोग मामला नहीं.',
    bn: 'আপনার এলাকায় এখনও কোনো রোগের কেস নেই.',
  },
  'disease.potato_late_blight': {
    en: 'Late blight',
    mr: 'उशिरा करपा',
    hi: 'पछेती झुलसा',
    bn: 'লেট ব্লাইট',
  },
  'disease.potato_early_blight': {
    en: 'Early blight',
    mr: 'लवकर करपा',
    hi: 'अगेती झुलसा',
    bn: 'আর্লি ব্লাইট',
  },
  'home.nearby.none': {
    en: 'No cases reported near you in the last 30 days.',
    mr: 'गेल्या ३० दिवसांत जवळ कोणतेही प्रकरण नाही.',
    hi: 'पिछले ३० दिनों में पास कोई मामला नहीं.',
    bn: 'গত ৩০ দিনে কাছে কোনো কেস নেই.',
  },
  'home.weather.title': { en: 'Weather now', mr: 'आताचे हवामान', hi: 'अभी का मौसम', bn: 'এখনকার আবহাওয়া' },
  'home.weather.line': {
    en: '{temp}°C, {hum}% humidity',
    mr: '{temp}°C, {hum}% आर्द्रता',
    hi: '{temp}°C, {hum}% नमी',
    bn: '{temp}°C, {hum}% আর্দ্রতা',
  },
  'home.dataThin': {
    en: 'Early data. This alert gets sharper as more weather and local reports build up.',
    mr: 'सुरुवातीचा डेटा. अधिक हवामान व स्थानिक नोंदी जमल्यावर हा इशारा अधिक अचूक होतो.',
    hi: 'शुरुआती डेटा. ज़्यादा मौसम और स्थानीय रिपोर्ट आने पर यह चेतावनी सटीक होगी.',
    bn: 'প্রাথমিক তথ্য. আরও আবহাওয়া ও স্থানীয় রিপোর্ট এলে সতর্কতা আরও নিখুঁত হবে.',
  },
  'home.disclaimer': {
    en: 'This is a warning to look, not a diagnosis. Photograph a plant to be sure.',
    mr: 'हा पाहण्याचा इशारा आहे, निदान नाही. खात्रीसाठी झाडाचा फोटो काढा.',
    hi: 'यह देखने की चेतावनी है, निदान नहीं. पक्का करने को पौधे की फोटो लें.',
    bn: 'এটি দেখার সতর্কতা, রোগ নির্ণয় নয়. নিশ্চিত হতে গাছের ছবি তুলুন.',
  },
  'home.why': { en: 'Why this alert', mr: 'हा इशारा का', hi: 'यह चेतावनी क्यों', bn: 'কেন এই সতর্কতা' },
  'home.locate': {
    en: 'Show alerts for my field',
    mr: 'माझ्या शेतासाठी इशारे दाखवा',
    hi: 'मेरे खेत के लिए चेतावनी दिखाएँ',
    bn: 'আমার জমির সতর্কতা দেখান',
  },
  'home.myLocation': { en: 'My location', mr: 'माझे स्थान', hi: 'मेरा स्थान', bn: 'আমার অবস্থান' },
  'home.source': { en: 'Data', mr: 'डेटा', hi: 'डेटा', bn: 'ডেটা' },
  'home.source.demo': { en: 'Demo + live', mr: 'डेमो + थेट', hi: 'डेमो + लाइव', bn: 'ডেমো + লাইভ' },
  'home.source.live': { en: 'Live only', mr: 'फक्त थेट', hi: 'सिर्फ़ लाइव', bn: 'শুধু লাইভ' },
  'home.source.demoNote': {
    en: 'Showing seeded demo cases alongside real reports, so the alert is populated for a walkthrough.',
    mr: 'खऱ्या नोंदींसह डेमो प्रकरणे दाखवत आहे, त्यामुळे इशारा भरलेला दिसतो.',
    hi: 'असली रिपोर्ट के साथ डेमो मामले दिखा रहे हैं, ताकि चेतावनी भरी दिखे.',
    bn: 'আসল রিপোর্টের সঙ্গে ডেমো কেস দেখানো হচ্ছে, যাতে সতর্কতা ভরা দেখায়.',
  },
  'home.source.liveNote': {
    en: 'Live only: seeded demo cases are excluded, so nearby counts come from real reports.',
    mr: 'फक्त थेट: डेमो प्रकरणे वगळली, जवळचे आकडे खऱ्या नोंदींतून येतात.',
    hi: 'सिर्फ़ लाइव: डेमो मामले हटाए, पास के आँकड़े असली रिपोर्ट से हैं.',
    bn: 'শুধু লাইভ: ডেমো কেস বাদ, কাছের সংখ্যা আসল রিপোর্ট থেকে.',
  },

  'result.diagnosis': { en: 'Diagnosis', mr: 'निदान', hi: 'निदान', bn: 'রোগ নির্ণয়' },
  'result.confidence': { en: 'Confidence', mr: 'खात्री', hi: 'भरोसा', bn: 'নিশ্চয়তা' },
  'result.confident': { en: 'Confident', mr: 'खात्रीशीर', hi: 'भरोसेमंद', bn: 'নিশ্চিত' },
  'result.escalated': {
    en: 'Needs an expert',
    mr: 'तज्ज्ञ हवा',
    hi: 'विशेषज्ञ चाहिए',
    bn: 'বিশেষজ্ঞ দরকার',
  },
  'result.nothing': {
    en: 'Nothing found',
    mr: 'काही आढळले नाही',
    hi: 'कुछ नहीं मिला',
    bn: 'কিছু মেলেনি',
  },
  'result.newCheck': {
    en: 'Check another photo',
    mr: 'दुसरा फोटो तपासा',
    hi: 'दूसरी फोटो जाँचें',
    bn: 'আরেকটি ছবি দেখুন',
  },

  'common.loading': { en: 'Loading', mr: 'लोड होत आहे', hi: 'लोड हो रहा है', bn: 'লোড হচ্ছে' },
  'common.cancel': { en: 'Cancel', mr: 'रद्द करा', hi: 'रद्द करें', bn: 'বাতিল' },
  'common.error': { en: 'Something went wrong', mr: 'काहीतरी चुकले', hi: 'कुछ गड़बड़ हुई', bn: 'কিছু ভুল হয়েছে' },
  'common.optional': { en: 'optional', mr: 'ऐच्छिक', hi: 'वैकल्पिक', bn: 'ঐচ্ছিক' },
  'common.none': { en: 'Nothing yet', mr: 'अद्याप काही नाही', hi: 'अभी कुछ नहीं', bn: 'এখনও কিছু নেই' },
  'common.window': { en: 'Period', mr: 'कालावधी', hi: 'अवधि', bn: 'সময়কাল' },
  'common.days7': { en: 'Last 7 days', mr: 'गेले ७ दिवस', hi: 'पिछले ७ दिन', bn: 'গত ৭ দিন' },
  'common.days30': { en: 'Last 30 days', mr: 'गेले ३० दिवस', hi: 'पिछले ३० दिन', bn: 'গত ৩০ দিন' },
  'common.days90': { en: 'Last 90 days', mr: 'गेले ९० दिवस', hi: 'पिछले ९० दिन', bn: 'গত ৯০ দিন' },
  'common.allDistricts': { en: 'All districts', mr: 'सर्व जिल्हे', hi: 'सभी ज़िले', bn: 'সব জেলা' },

  'advisory.title': { en: 'What to do', mr: 'काय करावे', hi: 'क्या करें', bn: 'কী করবেন' },
  'advisory.product': { en: 'Product', mr: 'उत्पादन', hi: 'उत्पाद', bn: 'পণ্য' },
  'advisory.dose': { en: 'Dose', mr: 'मात्रा', hi: 'मात्रा', bn: 'মাত্রা' },
  'advisory.notes': { en: 'Notes', mr: 'सूचना', hi: 'सूचना', bn: 'নোট' },
  'advisory.whyExpert': {
    en: 'Why an expert is needed',
    mr: 'तज्ज्ञ का हवा',
    hi: 'विशेषज्ञ क्यों चाहिए',
    bn: 'কেন বিশেষজ্ঞ দরকার',
  },
  'advisory.sources': { en: 'Sources', mr: 'स्रोत', hi: 'स्रोत', bn: 'সূত্র' },

  'scan.help': {
    en: 'Point the camera at the leaf. Hold still until a result settles.',
    mr: 'कॅमेरा पानाकडे धरा. निकाल स्थिर होईपर्यंत स्थिर धरा.',
    hi: 'कैमरा पत्ती की ओर रखें. नतीजा स्थिर होने तक स्थिर रखें.',
    bn: 'ক্যামেরা পাতার দিকে ধরুন. ফল স্থির না হওয়া পর্যন্ত স্থির থাকুন.',
  },
  'scan.start': { en: 'Start camera', mr: 'कॅमेरा सुरू करा', hi: 'कैमरा शुरू करें', bn: 'ক্যামেরা চালু করুন' },
  'scan.stop': { en: 'Stop camera', mr: 'कॅमेरा बंद करा', hi: 'कैमरा बंद करें', bn: 'ক্যামেরা বন্ধ করুন' },
  'scan.camera': { en: 'Camera', mr: 'कॅमेरा', hi: 'कैमरा', bn: 'ক্যামেরা' },
  'scan.cameraAuto': { en: 'Automatic', mr: 'स्वयंचलित', hi: 'स्वचालित', bn: 'স্বয়ংক্রিয়' },
  'scan.pressStart': {
    en: 'Tap Start camera',
    mr: 'कॅमेरा सुरू करा दाबा',
    hi: 'कैमरा शुरू करें दबाएँ',
    bn: 'ক্যামেরা চালু করুন চাপুন',
  },
  'scan.denied': {
    en: 'Camera blocked',
    mr: 'कॅमेरा अडवला',
    hi: 'कैमरा रुका है',
    bn: 'ক্যামেরা বন্ধ',
  },
  'scan.deniedHelp': {
    en: 'Allow the camera in your browser settings, then tap Start again.',
    mr: 'ब्राउझर सेटिंगमध्ये कॅमेरा परवानगी द्या, मग पुन्हा सुरू करा दाबा.',
    hi: 'ब्राउज़र सेटिंग में कैमरा अनुमति दें, फिर शुरू करें दबाएँ.',
    bn: 'ব্রাউজার সেটিংসে ক্যামেরার অনুমতি দিন, তারপর আবার চালু করুন.',
  },
  'scan.holdSteady': { en: 'Hold still', mr: 'स्थिर धरा', hi: 'स्थिर रखें', bn: 'স্থির থাকুন' },
  'scan.settling': { en: 'Settling', mr: 'स्थिर होत आहे', hi: 'स्थिर हो रहा है', bn: 'স্থির হচ্ছে' },
  'scan.verdict': { en: 'Result', mr: 'निकाल', hi: 'नतीजा', bn: 'ফল' },
  'scan.accept': { en: 'Accept', mr: 'स्वीकारा', hi: 'स्वीकारें', bn: 'গ্রহণ করুন' },
  'scan.discard': { en: 'Discard', mr: 'नाकारा', hi: 'हटाएँ', bn: 'বাতিল করুন' },
  'scan.accepted': { en: 'Scan saved', mr: 'स्कॅन जतन झाले', hi: 'स्कैन सहेजा गया', bn: 'স্ক্যান সংরক্ষিত' },
  'scan.scanAgain': {
    en: 'Scan another plant',
    mr: 'दुसरे झाड स्कॅन करा',
    hi: 'दूसरा पौधा स्कैन करें',
    bn: 'আরেকটি গাছ স্ক্যান করুন',
  },
  'scan.acceptExplain': {
    en: 'Accept saves this frame as a case with full advice. Discard stores nothing.',
    mr: 'स्वीकारल्यास ही फ्रेम संपूर्ण सल्ल्यासह जतन होते. नाकारल्यास काहीही साठवले जात नाही.',
    hi: 'स्वीकारने पर यह फ्रेम पूरी सलाह के साथ सहेजी जाती है. हटाने पर कुछ नहीं रखा जाता.',
    bn: 'গ্রহণ করলে এই ফ্রেম সম্পূর্ণ পরামর্শসহ সংরক্ষিত হয়. বাতিল করলে কিছুই থাকে না.',
  },
  'scan.agreement': { en: 'Agreement', mr: 'सहमती', hi: 'सहमति', bn: 'সঙ্গতি' },
  'scan.frames': { en: 'frames', mr: 'फ्रेम', hi: 'फ़्रेम', bn: 'ফ্রেম' },
  'scan.noDetection': {
    en: 'Nothing recognised',
    mr: 'काही ओळखले नाही',
    hi: 'कुछ पहचाना नहीं',
    bn: 'কিছু চেনা গেল না',
  },
  'scan.noDetectionHelp': {
    en: 'Move closer to a sick leaf. The problem may also be outside the three types this model knows.',
    mr: 'रोगट पानाजवळ जा. समस्या या प्रारूपाच्या तीन प्रकारांबाहेरची असू शकते.',
    hi: 'बीमार पत्ती के पास जाएँ. समस्या मॉडल के तीन प्रकारों से बाहर भी हो सकती है.',
    bn: 'অসুস্থ পাতার কাছে যান. সমস্যাটি মডেলের তিন ধরনের বাইরেও হতে পারে.',
  },
  'scan.scanningHelp': {
    en: 'Keep the leaf filling the frame and hold still.',
    mr: 'पान चौकटभर ठेवा आणि स्थिर धरा.',
    hi: 'पत्ती को फ्रेम में भरा रखें और स्थिर रहें.',
    bn: 'পাতা ফ্রেম জুড়ে রাখুন আর স্থির থাকুন.',
  },
  'scan.unstableHelp': {
    en: 'Readings still disagree. Move a little closer and hold still.',
    mr: 'वाचने अजून जुळत नाहीत. थोडे जवळ जा आणि स्थिर धरा.',
    hi: 'रीडिंग अभी मेल नहीं खा रहीं. थोड़ा पास जाएँ और स्थिर रहें.',
    bn: 'রিডিং এখনও মিলছে না. একটু কাছে যান আর স্থির থাকুন.',
  },
  'scan.qualityWait': {
    en: 'Image is not clear enough. Fix the light or hold steadier.',
    mr: 'चित्र पुरेसे स्पष्ट नाही. प्रकाश सुधारा किंवा अधिक स्थिर धरा.',
    hi: 'तस्वीर पर्याप्त साफ़ नहीं. रोशनी ठीक करें या स्थिर रखें.',
    bn: 'ছবি যথেষ্ট স্পষ্ট নয়. আলো ঠিক করুন বা স্থির রাখুন.',
  },
  'scan.onDevice': {
    en: 'On phone, works offline',
    mr: 'फोनवर, ऑफलाइन चालते',
    hi: 'फोन पर, ऑफ़लाइन चलता है',
    bn: 'ফোনে, অফলাইনে চলে',
  },
  'scan.serverMode': { en: 'Server mode', mr: 'सर्व्हरवर', hi: 'सर्वर पर', bn: 'সার্ভারে' },
  'scan.noModel': {
    en: 'No model installed, so live scan is off.',
    mr: 'मॉडेल स्थापित नाही, त्यामुळे थेट स्कॅन बंद आहे.',
    hi: 'मॉडल स्थापित नहीं है, इसलिए लाइव स्कैन बंद है.',
    bn: 'মডেল ইনস্টল নেই, তাই লাইভ স্ক্যান বন্ধ.',
  },
  'scan.noModelHelp': {
    en: 'You can still send a photo from Check crop.',
    mr: 'तुम्ही पीक तपासा येथून फोटो पाठवू शकता.',
    hi: 'आप फसल जाँचें से फोटो भेज सकते हैं.',
    bn: 'আপনি ফসল দেখুন থেকে ছবি পাঠাতে পারেন.',
  },
  'scan.airflow': { en: 'Airflow', mr: 'हवेची हालचाल', hi: 'हवा की गति', bn: 'বাতাসের চলাচল' },
  'scan.airflow.tag': { en: 'experimental', mr: 'प्रायोगिक', hi: 'प्रायोगिक', bn: 'পরীক্ষামূলক' },
  'scan.airflow.calibrating': { en: 'measuring…', mr: 'मोजत आहे…', hi: 'माप रहे हैं…', bn: 'মাপা হচ্ছে…' },
  'scan.airflow.still': { en: 'Still', mr: 'शांत', hi: 'शांत', bn: 'স্থির' },
  'scan.airflow.light': { en: 'Light', mr: 'हलकी', hi: 'हल्की', bn: 'হালকা' },
  'scan.airflow.breezy': { en: 'Breezy', mr: 'वारेदार', hi: 'हवादार', bn: 'বাতাসী' },
  'scan.airflow.explain': {
    en: 'Rough in-field airflow from how leaves move between frames. Still air keeps leaves wet longer and raises blight risk. A relative hint, not a wind-speed sensor.',
    mr: 'फ्रेममध्ये पाने कशी हलतात यावरून शेतातील अंदाजे हवा. शांत हवा पाने जास्त वेळ ओली ठेवते व करपा धोका वाढवते. हा सापेक्ष इशारा आहे, वाऱ्याचा वेग मोजणारे यंत्र नाही.',
    hi: 'फ्रेम के बीच पत्तियों की हलचल से खेत की मोटी हवा का अंदाज़ा. शांत हवा पत्तियों को ज़्यादा देर गीला रखती है और झुलसा जोखिम बढ़ाती है. यह सापेक्ष संकेत है, हवा-गति सेंसर नहीं.',
    bn: 'ফ্রেমের মধ্যে পাতা কীভাবে নড়ে তা থেকে জমির আনুমানিক বাতাস. স্থির বাতাস পাতা বেশিক্ষণ ভেজা রাখে ও ব্লাইট ঝুঁকি বাড়ায়. এটি আপেক্ষিক ইঙ্গিত, বাতাসের গতি মাপার যন্ত্র নয়.',
  },
  'scan.howItWorks': { en: 'How this works', mr: 'हे कसे चालते', hi: 'यह कैसे काम करता है', bn: 'এটি কীভাবে কাজ করে' },
  'scan.how1': {
    en: 'Blurry or dark frames are thrown away first.',
    mr: 'अस्पष्ट किंवा काळोख्या फ्रेम आधीच टाकून दिल्या जातात.',
    hi: 'धुंधले या अँधेरे फ़्रेम पहले ही हटा दिए जाते हैं.',
    bn: 'ঝাপসা বা অন্ধকার ফ্রেম আগেই বাদ যায়.',
  },
  'scan.how2': {
    en: 'A result shows only when several frames agree.',
    mr: 'अनेक फ्रेम जुळल्यावरच निकाल दिसतो.',
    hi: 'कई फ़्रेम मेल खाने पर ही नतीजा दिखता है.',
    bn: 'একাধিক ফ্রেম মিললেই কেবল ফল দেখায়.',
  },
  'scan.how3': {
    en: 'Nothing is saved until you tap Accept.',
    mr: 'स्वीकारा दाबेपर्यंत काहीही जतन होत नाही.',
    hi: 'स्वीकारें दबाने तक कुछ नहीं सहेजा जाता.',
    bn: 'গ্রহণ করুন না চাপলে কিছুই সংরক্ষিত হয় না.',
  },

  'chat.open': { en: 'Ask CropGuard', mr: 'क्रॉपगार्डला विचारा', hi: 'क्रॉपगार्ड से पूछें', bn: 'ক্রপগার্ডকে জিজ্ঞাসা করুন' },
  'chat.title': { en: 'CropGuard Assistant', mr: 'क्रॉपगार्ड सहायक', hi: 'क्रॉपगार्ड सहायक', bn: 'ক্রপগার্ড সহায়ক' },
  'chat.subtitle': {
    en: 'Ask about potato disease or how to use the app',
    mr: 'बटाटा रोग किंवा अ‍ॅप वापराबद्दल विचारा',
    hi: 'आलू रोग या ऐप उपयोग के बारे में पूछें',
    bn: 'আলুর রোগ বা অ্যাপ ব্যবহার নিয়ে জিজ্ঞাসা করুন',
  },
  'chat.greeting': {
    en: 'Hi! I can help with potato diseases, safe pesticide use, and using CropGuard. What would you like to know?',
    mr: 'नमस्कार! बटाटा रोग, सुरक्षित कीटकनाशक वापर आणि क्रॉपगार्ड वापरण्यात मी मदत करू शकतो. काय जाणून घ्यायचे आहे?',
    hi: 'नमस्ते! मैं आलू रोग, सुरक्षित कीटनाशक उपयोग और क्रॉपगार्ड चलाने में मदद कर सकता हूँ. आप क्या जानना चाहेंगे?',
    bn: 'নমস্কার! আমি আলুর রোগ, নিরাপদ কীটনাশক ব্যবহার এবং ক্রপগার্ড চালাতে সাহায্য করতে পারি. আপনি কী জানতে চান?',
  },
  'chat.placeholder': { en: 'Type your question…', mr: 'तुमचा प्रश्न लिहा…', hi: 'अपना सवाल लिखें…', bn: 'আপনার প্রশ্ন লিখুন…' },
  'chat.send': { en: 'Send', mr: 'पाठवा', hi: 'भेजें', bn: 'পাঠান' },
  'chat.close': { en: 'Close chat', mr: 'चॅट बंद करा', hi: 'चैट बंद करें', bn: 'চ্যাট বন্ধ করুন' },
  'chat.thinking': { en: 'Thinking…', mr: 'विचार करत आहे…', hi: 'सोच रहा है…', bn: 'ভাবছে…' },
  'chat.error': {
    en: 'Could not reach the assistant. Please try again.',
    mr: 'सहायकाशी संपर्क झाला नाही. पुन्हा प्रयत्न करा.',
    hi: 'सहायक से संपर्क नहीं हुआ. दोबारा कोशिश करें.',
    bn: 'সহায়কের সঙ্গে সংযোগ হয়নি. আবার চেষ্টা করুন.',
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
// Lets a test catch a language that has silently fallen behind.
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
