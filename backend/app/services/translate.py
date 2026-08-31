"""Multilingual advisory layer. Marathi is the priority language (Maharashtra),
Hindi second, English the source.

Design decision that matters: the advisory is **composed from structured
message templates**, each of which exists in en/mr/hi. That means a farmer gets
a genuinely Marathi advisory with no API key, no network, and no LLM cost --
important for a rural deployment and for offline capability. The LLM is used
only to translate free-text knowledge-base excerpts, and when it is not
available those excerpts are returned in English and clearly flagged rather
than silently dropped.

Agricultural terminology is not something to machine-translate loosely. The
Marathi and Hindi strings below use the terms extension services actually use
(karpa for blight, phavarni for spraying) so an advisory reads as a Krishi
Sahayak would say it.
"""
from __future__ import annotations

import logging

from app.config import settings

log = logging.getLogger(__name__)

LANGUAGE_NAMES = {
    "en": "English",
    "mr": "मराठी (Marathi)",
    "hi": "हिन्दी (Hindi)",
    "bn": "বাংলা (Bengali)",
}

# ----------------------------------------------------------------------
# Message catalog. Keys are stable ids; values are format strings.
# ----------------------------------------------------------------------
CATALOG: dict[str, dict[str, str]] = {
    "heading.diagnosis": {
        "en": "Diagnosis",
        "mr": "निदान",
        "hi": "निदान",
        "bn": "রোগ নির্ণয়",
    },
    "heading.risk": {
        "en": "Weather-based risk",
        "mr": "हवामान आधारित धोका",
        "hi": "मौसम आधारित जोखिम",
        "bn": "আবহাওয়া ভিত্তিক ঝুঁকি",
    },
    "heading.immediate": {
        "en": "Do this now",
        "mr": "आत्ता हे करा",
        "hi": "अभी यह करें",
        "bn": "এখনই এটি করুন",
    },
    "heading.chemical": {
        "en": "If chemical control is needed",
        "mr": "रासायनिक फवारणी आवश्यक असल्यास",
        "hi": "यदि रासायनिक छिड़काव आवश्यक हो",
        "bn": "রাসায়নিক প্রয়োগ প্রয়োজন হলে",
    },
    "heading.cultural": {
        "en": "Preventive and cultural practice",
        "mr": "प्रतिबंधात्मक व मशागतीचे उपाय",
        "hi": "निवारक एवं कृषि पद्धतियाँ",
        "bn": "প্রতিরোধমূলক ও চাষাবাদ ব্যবস্থা",
    },
    "heading.safety": {
        "en": "Safe input usage",
        "mr": "निविष्ठांचा सुरक्षित वापर",
        "hi": "निवेश का सुरक्षित उपयोग",
        "bn": "উপকরণের নিরাপদ ব্যবহার",
    },
    "heading.referral": {
        "en": "Expert referral",
        "mr": "तज्ज्ञांकडे पाठवा",
        "hi": "विशेषज्ञ को भेजें",
        "bn": "বিশেষজ্ঞের কাছে পাঠান",
    },
    "heading.followup": {
        "en": "Follow-up",
        "mr": "पुढील तपासणी",
        "hi": "अनुवर्ती जाँच",
        "bn": "পরবর্তী পরিদর্শন",
    },
    "risk.low": {
        "en": "LOW",
        "mr": "कमी",
        "hi": "कम",
        "bn": "কম",
    },
    "risk.medium": {
        "en": "MEDIUM",
        "mr": "मध्यम",
        "hi": "मध्यम",
        "bn": "মাঝারি",
    },
    "risk.high": {
        "en": "HIGH",
        "mr": "जास्त",
        "hi": "उच्च",
        "bn": "বেশি",
    },
    "urgency.routine": {
        "en": "Routine",
        "mr": "नियमित",
        "hi": "सामान्य",
        "bn": "নিয়মিত",
    },
    "urgency.soon": {
        "en": "Act within 48 hours",
        "mr": "४८ तासांत कार्यवाही करा",
        "hi": "48 घंटे में कार्रवाई करें",
        "bn": "৪৮ ঘণ্টার মধ্যে ব্যবস্থা নিন",
    },
    "urgency.urgent": {
        "en": "Act today",
        "mr": "आजच कार्यवाही करा",
        "hi": "आज ही कार्रवाई करें",
        "bn": "আজই ব্যবস্থা নিন",
    },
    "diag.detected": {
        "en": "{disease} detected with {confidence} confidence.",
        "mr": "{disease} आढळले, खात्री {confidence}.",
        "hi": "{disease} पाया गया, विश्वास {confidence}.",
        "bn": "{disease} শনাক্ত হয়েছে, নিশ্চয়তা {confidence}।",
    },
    "diag.healthy": {
        "en": "No disease or pest symptoms were detected in this photograph.",
        "mr": "या छायाचित्रात रोग किंवा किडीची लक्षणे आढळली नाहीत.",
        "hi": "इस तस्वीर में रोग या कीट के लक्षण नहीं मिले।",
        "bn": "এই ছবিতে রোগ বা পোকার কোনো লক্ষণ পাওয়া যায়নি।",
    },
    "diag.uncertain": {
        "en": "The diagnosis is uncertain. Treat it as provisional until an officer confirms it.",
        "mr": "निदान निश्चित नाही. अधिकाऱ्याने खात्री करेपर्यंत ते तात्पुरते समजा.",
        "hi": "निदान अनिश्चित है। अधिकारी की पुष्टि तक इसे अस्थायी मानें।",
        "bn": "রোগ নির্ণয় নিশ্চিত নয়। কর্মকর্তা নিশ্চিত না করা পর্যন্ত এটি অস্থায়ী ধরুন।",
    },
    "diag.forecast_only": {
        "en": "No photograph was submitted. This is a weather-based forecast for your field, not a diagnosis.",
        "mr": "छायाचित्र पाठवलेले नाही. हे आपल्या शेतासाठी हवामानावर आधारित पूर्वानुमान आहे, निदान नाही.",
        "hi": "कोई तस्वीर नहीं भेजी गई। यह आपके खेत के लिए मौसम आधारित पूर्वानुमान है, निदान नहीं।",
        "bn": "কোনো ছবি পাঠানো হয়নি। এটি আপনার জমির জন্য আবহাওয়া ভিত্তিক পূর্বাভাস, রোগ নির্ণয় নয়।",
    },
    "diag.unavailable": {
        "en": "Automated diagnosis is unavailable on this deployment.",
        "mr": "या प्रणालीवर स्वयंचलित निदान उपलब्ध नाही.",
        "hi": "इस प्रणाली पर स्वचालित निदान उपलब्ध नहीं है।",
        "bn": "এই ব্যবস্থায় স্বয়ংক্রিয় রোগ নির্ণয় পাওয়া যাচ্ছে না।",
    },
    "risk.sentence": {
        "en": "{threat} risk is {level} for the next few days.",
        "mr": "पुढील काही दिवसांसाठी {threat} चा धोका {level} आहे.",
        "hi": "अगले कुछ दिनों के लिए {threat} का जोखिम {level} है।",
        "bn": "আগামী কয়েক দিনের জন্য {threat} এর ঝুঁকি {level}।",
    },
    "risk.smith_fired": {
        "en": "Late blight infection conditions (Smith Period) have been met.",
        "mr": "उशिरा येणाऱ्या करप्याच्या संसर्गाची स्थिती (स्मिथ कालावधी) पूर्ण झाली आहे.",
        "hi": "पछेती झुलसा संक्रमण की स्थिति (स्मिथ अवधि) पूरी हो चुकी है।",
        "bn": "নাবি ধসা সংক্রমণের পরিস্থিতি (স্মিথ পিরিয়ড) সম্পূর্ণ হয়েছে।",
    },
    "action.no_spray": {
        "en": "No pesticide spray is needed right now.",
        "mr": "सध्या कोणतीही कीटकनाशक फवारणी करण्याची गरज नाही.",
        "hi": "अभी किसी कीटनाशक छिड़काव की आवश्यकता नहीं है।",
        "bn": "এখন কোনো কীটনাশক স্প্রে করার প্রয়োজন নেই।",
    },
    "action.protectant": {
        "en": "Apply a protectant fungicide before symptoms appear.",
        "mr": "लक्षणे दिसण्यापूर्वी संरक्षक बुरशीनाशकाची फवारणी करा.",
        "hi": "लक्षण दिखने से पहले सुरक्षात्मक फफूंदनाशक का छिड़काव करें।",
        "bn": "লক্ষণ দেখা দেওয়ার আগেই প্রতিরোধক ছত্রাকনাশক স্প্রে করুন।",
    },
    "action.remove_infected": {
        "en": "Remove and destroy infected plants and leaves; do not leave them in the field.",
        "mr": "रोगग्रस्त झाडे व पाने काढून नष्ट करा; ती शेतात ठेवू नका.",
        "hi": "रोगग्रस्त पौधे और पत्तियाँ हटाकर नष्ट करें; उन्हें खेत में न छोड़ें।",
        "bn": "আক্রান্ত গাছ ও পাতা তুলে নষ্ট করুন; জমিতে ফেলে রাখবেন না।",
    },
    "action.stop_evening_irrigation": {
        "en": "Stop evening irrigation so the crop canopy dries before night.",
        "mr": "संध्याकाळचे पाणी देणे थांबवा, म्हणजे रात्रीपूर्वी पीक कोरडे होईल.",
        "hi": "शाम की सिंचाई बंद करें ताकि रात से पहले फसल सूख जाए।",
        "bn": "সন্ধ্যায় সেচ দেওয়া বন্ধ করুন, যাতে রাতের আগে গাছ শুকিয়ে যায়।",
    },
    "action.scout": {
        "en": "Scout the field twice a week, checking the lower leaves first.",
        "mr": "आठवड्यातून दोनदा शेताची पाहणी करा, प्रथम खालची पाने तपासा.",
        "hi": "सप्ताह में दो बार खेत का निरीक्षण करें, पहले निचली पत्तियाँ देखें।",
        "bn": "সপ্তাহে দুবার জমি পরিদর্শন করুন, প্রথমে নিচের পাতা দেখুন।",
    },
    "action.earthing_up": {
        "en": "Earth up the ridges properly so tubers stay covered.",
        "mr": "बटाटे झाकले जातील अशा प्रकारे मातीची भर व्यवस्थित लावा.",
        "hi": "मेड़ों पर ठीक से मिट्टी चढ़ाएँ ताकि कंद ढके रहें।",
        "bn": "আলু ঢাকা থাকে এমনভাবে সারিতে ভালো করে মাটি তুলে দিন।",
    },
    "action.check_traps": {
        "en": "Check pheromone traps and record the catch count.",
        "mr": "कामगंध सापळे तपासा आणि पकडलेल्या किडींची नोंद करा.",
        "hi": "फेरोमोन ट्रैप जाँचें और पकड़ी गई संख्या दर्ज करें।",
        "bn": "ফেরোমোন ফাঁদ পরীক্ষা করুন এবং ধরা পড়া পোকার সংখ্যা লিখে রাখুন।",
    },
    "action.rotate_chemistry": {
        "en": "Alternate fungicide groups between sprays; never spray the same product twice in a row.",
        "mr": "प्रत्येक फवारणीत बुरशीनाशकाचा गट बदला; एकच औषध सलग दोनदा फवारू नका.",
        "hi": "हर छिड़काव में फफूंदनाशक समूह बदलें; एक ही दवा लगातार दो बार न छिड़कें।",
        "bn": "প্রতিবার স্প্রেতে ছত্রাকনাশকের গ্রুপ বদলান; একই ওষুধ পরপর দুবার স্প্রে করবেন না।",
    },
    "safety.label_dose": {
        "en": "Use only the dose printed on the label. A higher dose does not work better.",
        "mr": "लेबलवर छापलेल्याच मात्रेचा वापर करा. जास्त मात्रा अधिक परिणामकारक नसते.",
        "hi": "केवल लेबल पर छपी मात्रा का उपयोग करें। अधिक मात्रा बेहतर काम नहीं करती।",
        "bn": "লেবেলে লেখা মাত্রাই ব্যবহার করুন। বেশি মাত্রা ভালো কাজ করে না।",
    },
    "safety.ppe": {
        "en": "Wear gloves, a mask, full-sleeve clothes and eye protection while spraying.",
        "mr": "फवारणी करताना हातमोजे, मास्क, पूर्ण बाह्यांचे कपडे व डोळ्यांचे संरक्षण वापरा.",
        "hi": "छिड़काव करते समय दस्ताने, मास्क, पूरी बाँह के कपड़े और चश्मा पहनें।",
        "bn": "স্প্রে করার সময় দস্তানা, মাস্ক, ফুল হাতা জামা ও চোখের সুরক্ষা ব্যবহার করুন।",
    },
    "safety.wind": {
        "en": "Spray with the wind behind you, in the early morning or evening.",
        "mr": "वाऱ्याच्या दिशेने पाठ करून, सकाळी लवकर किंवा संध्याकाळी फवारणी करा.",
        "hi": "हवा को पीठ पीछे रखकर, सुबह जल्दी या शाम को छिड़काव करें।",
        "bn": "বাতাস পিঠের দিকে রেখে, ভোরে বা সন্ধ্যায় স্প্রে করুন।",
    },
    "safety.phi": {
        "en": "Observe the pre-harvest interval on the label before harvesting.",
        "mr": "काढणीपूर्वी लेबलवरील प्रतीक्षा कालावधी (PHI) पाळा.",
        "hi": "कटाई से पहले लेबल पर दिए प्रतीक्षा अंतराल (PHI) का पालन करें।",
        "bn": "ফসল কাটার আগে লেবেলে দেওয়া অপেক্ষার সময় (PHI) মেনে চলুন।",
    },
    "safety.licensed_dealer": {
        "en": "Buy only from a licensed dealer and keep the bill.",
        "mr": "फक्त परवानाधारक विक्रेत्याकडूनच खरेदी करा आणि पावती जपून ठेवा.",
        "hi": "केवल लाइसेंसधारी विक्रेता से खरीदें और बिल रखें।",
        "bn": "কেবল লাইসেন্সপ্রাপ্ত বিক্রেতার কাছ থেকে কিনুন এবং রসিদ রাখুন।",
    },
    "safety.container": {
        "en": "Triple-rinse and puncture empty containers. Never reuse them.",
        "mr": "रिकाम्या डब्यांना तीनदा धुवा व छिद्र पाडा. त्यांचा पुनर्वापर करू नका.",
        "hi": "खाली डिब्बों को तीन बार धोकर छेद करें। इनका पुनः उपयोग न करें।",
        "bn": "খালি কৌটা তিনবার ধুয়ে ছিদ্র করে দিন। কখনও পুনরায় ব্যবহার করবেন না।",
    },
    "safety.children": {
        "en": "Keep children, pregnant women and animals away from the sprayed field.",
        "mr": "फवारणी केलेल्या शेतापासून लहान मुले, गर्भवती महिला व जनावरे दूर ठेवा.",
        "hi": "छिड़काव किए खेत से बच्चों, गर्भवती महिलाओं और जानवरों को दूर रखें।",
        "bn": "স্প্রে করা জমি থেকে শিশু, গর্ভবতী নারী ও গবাদি পশুকে দূরে রাখুন।",
    },
    "safety.poison_helpline": {
        "en": "In case of poisoning, take the container label to the hospital. Helpline 1800-116-117.",
        "mr": "विषबाधा झाल्यास डब्याचे लेबल घेऊन रुग्णालयात जा. मदत क्रमांक १८००-११६-११७.",
        "hi": "विषाक्तता होने पर डिब्बे का लेबल लेकर अस्पताल जाएँ। हेल्पलाइन 1800-116-117।",
        "bn": "বিষক্রিয়া হলে কৌটার লেবেল নিয়ে হাসপাতালে যান। হেল্পলাইন ১৮০০-১১৬-১১৭।",
    },
    "referral.village": {
        "en": "Show this case to your village Krishi Sahayak (Agriculture Assistant).",
        "mr": "हे प्रकरण आपल्या गावातील कृषी सहाय्यकाला दाखवा.",
        "hi": "यह मामला अपने गाँव के कृषि सहायक को दिखाएँ।",
        "bn": "এই বিষয়টি আপনার গ্রামের কৃষি সহায়ককে দেখান।",
    },
    "referral.block": {
        "en": "Refer this case to the Taluka Agriculture Officer.",
        "mr": "हे प्रकरण तालुका कृषी अधिकाऱ्यांकडे पाठवा.",
        "hi": "यह मामला तालुका कृषि अधिकारी को भेजें।",
        "bn": "এই বিষয়টি তালুকা কৃষি অফিসারের কাছে পাঠান।",
    },
    "referral.district": {
        "en": "Report to the District Superintending Agriculture Officer - this may be an outbreak.",
        "mr": "जिल्हा अधीक्षक कृषी अधिकाऱ्यांना कळवा - हा उद्रेक असू शकतो.",
        "hi": "जिला अधीक्षक कृषि अधिकारी को सूचित करें - यह प्रकोप हो सकता है।",
        "bn": "জেলা কৃষি অফিসারকে জানান - এটি ব্যাপক প্রাদুর্ভাব হতে পারে।",
    },
    "referral.laboratory": {
        "en": "Send a plant sample to the Krishi Vigyan Kendra (KVK) laboratory for confirmation.",
        "mr": "खात्रीसाठी कृषी विज्ञान केंद्राच्या (KVK) प्रयोगशाळेत नमुना पाठवा.",
        "hi": "पुष्टि के लिए कृषि विज्ञान केंद्र (KVK) प्रयोगशाला में नमूना भेजें।",
        "bn": "নিশ্চিত হতে কৃষি বিজ্ঞান কেন্দ্রের (KVK) গবেষণাগারে নমুনা পাঠান।",
    },
    "referral.helpline": {
        "en": "Kisan Call Centre: 1800-180-1551 (toll-free).",
        "mr": "किसान कॉल सेंटर: १८००-१८०-१५५१ (निःशुल्क).",
        "hi": "किसान कॉल सेंटर: 1800-180-1551 (निःशुल्क)।",
        "bn": "কিষান কল সেন্টার: ১৮০০-১৮০-১৫৫১ (টোল ফ্রি)।",
    },
    "followup.scheduled": {
        "en": "Re-inspect the field on {date} and record the result in this app.",
        "mr": "{date} रोजी शेताची पुन्हा पाहणी करा आणि निकाल या ॲपमध्ये नोंदवा.",
        "hi": "{date} को खेत का पुनः निरीक्षण करें और परिणाम इस ऐप में दर्ज करें।",
        "bn": "{date} তারিখে জমি আবার পরিদর্শন করুন এবং ফলাফল এই অ্যাপে লিখুন।",
    },
    "followup.why": {
        "en": "If the problem is unchanged or worse at follow-up, do not repeat the same spray - refer it.",
        "mr": "पुढील तपासणीत सुधारणा नसल्यास तीच फवारणी पुन्हा करू नका - तज्ज्ञांकडे पाठवा.",
        "hi": "अनुवर्ती जाँच में सुधार न हो तो वही छिड़काव दोहराएँ नहीं - विशेषज्ञ को भेजें।",
        "bn": "পরবর্তী পরিদর্শনে উন্নতি না হলে একই স্প্রে আবার করবেন না - বিশেষজ্ঞের কাছে পাঠান।",
    },
    "chemical.non_chemical_first": {
        "en": "The knowledge base recommends monitoring and cultural control for this threat rather than a routine spray. Consult an extension officer before using any insecticide.",
        "mr": "या धोक्यासाठी नियमित फवारणीऐवजी निरीक्षण व मशागतीचे उपाय सुचवले आहेत. कीटकनाशक वापरण्यापूर्वी कृषी अधिकाऱ्यांचा सल्ला घ्या.",
        "hi": "इस समस्या के लिए नियमित छिड़काव के बजाय निगरानी और कृषि उपाय सुझाए गए हैं। कीटनाशक उपयोग से पहले कृषि अधिकारी से सलाह लें।",
        "bn": "এই সমস্যার জন্য নিয়মিত স্প্রের বদলে পর্যবেক্ষণ ও চাষাবাদ ব্যবস্থার পরামর্শ দেওয়া হয়েছে। কীটনাশক ব্যবহারের আগে কৃষি অফিসারের পরামর্শ নিন।",
    },
    "chemical.withheld": {
        "en": "Dose recommendations are withheld until an extension officer confirms this diagnosis.",
        "mr": "कृषी अधिकाऱ्याने निदानाची खात्री करेपर्यंत मात्रेची शिफारस दिली जाणार नाही.",
        "hi": "कृषि अधिकारी द्वारा निदान की पुष्टि होने तक मात्रा की सिफारिश नहीं दी जाएगी।",
        "bn": "কৃষি অফিসার রোগ নির্ণয় নিশ্চিত না করা পর্যন্ত মাত্রার সুপারিশ দেওয়া হবে না।",
    },
    "chemical.not_required": {
        "en": "No chemical application is warranted right now.",
        "mr": "सध्या कोणत्याही रासायनिक फवारणीची गरज नाही.",
        "hi": "अभी किसी रासायनिक छिड़काव की आवश्यकता नहीं है।",
        "bn": "এখন কোনো রাসায়নিক প্রয়োগের প্রয়োজন নেই।",
    },
    "note.english_excerpt": {
        "en": "Detailed reference text below is in English.",
        "mr": "खालील सविस्तर संदर्भ मजकूर इंग्रजीत आहे.",
        "hi": "नीचे विस्तृत संदर्भ पाठ अंग्रेज़ी में है।",
        "bn": "নিচের বিস্তারিত তথ্য ইংরেজিতে দেওয়া আছে।",
    },
    "note.verify_local": {
        "en": "Confirm doses with your local KVK and the product label before mixing.",
        "mr": "मिश्रण करण्यापूर्वी मात्रा स्थानिक KVK व औषधाच्या लेबलवरून तपासा.",
        "hi": "मिलाने से पहले मात्रा स्थानीय KVK और उत्पाद लेबल से जाँचें।",
        "bn": "মেশানোর আগে মাত্রা স্থানীয় KVK ও ওষুধের লেবেল থেকে যাচাই করুন।",
    },
}


def t(key: str, lang: str = "en", **kwargs) -> str:
    """Translate a catalog key, falling back to English then to the key itself."""
    entry = CATALOG.get(key)
    if entry is None:
        log.warning("Missing translation key: %s", key)
        return key
    text = entry.get(lang) or entry.get("en") or key
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError):
        return text


def normalise_language(lang: str | None) -> str:
    if not lang:
        return settings.default_language
    lang = lang.strip().lower()[:2]
    return lang if lang in settings.languages else settings.default_language


def coverage() -> dict:
    """How complete the catalog is per language -- surfaced on /meta/languages
    so gaps are visible rather than silently falling back to English."""
    out = {}
    for lang in settings.languages:
        have = sum(1 for entry in CATALOG.values() if entry.get(lang))
        out[lang] = {
            "name": LANGUAGE_NAMES.get(lang, lang),
            "translated": have,
            "total": len(CATALOG),
            "coverage": round(have / len(CATALOG), 3) if CATALOG else 0.0,
        }
    return out


# ----------------------------------------------------------------------
# LLM translation for free-text KB excerpts (optional)
# ----------------------------------------------------------------------
def translate_free_text(text: str, lang: str) -> tuple[str, bool]:
    """Returns (text, was_translated). Falls back to English on any failure --
    a wrong pesticide dose in translation is worse than an English one."""
    if lang == "en" or not text.strip():
        return text, False
    if not settings.llm_enabled:
        return text, False
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        target = {"mr": "Marathi", "hi": "Hindi", "bn": "Bengali"}.get(lang, lang)
        msg = client.messages.create(
            model=settings.advisory_llm_model,
            max_tokens=1500,
            system=(
                "You translate Indian agricultural extension advisories. Translate into "
                f"{target} using the vocabulary a Krishi Sahayak would use with a farmer. "
                "Keep every number, dose, chemical name, product concentration and phone "
                "number exactly as written in the source, in Latin script. Do not add, remove "
                "or soften any safety instruction. Output only the translation."
            ),
            messages=[{"role": "user", "content": text}],
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip(), True
    except Exception as exc:
        log.warning("LLM translation failed (%s); returning English text", exc)
        return text, False
