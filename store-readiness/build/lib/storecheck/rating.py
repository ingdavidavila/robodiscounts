"""Age and content rating hints.

Apple's age rating questions ("Capabilities": unrestricted web access, user-generated content, messaging and
chat, shared location, advertising) are listed on the age ratings page, verified 2026-11-25. Google's IARC
questionnaire asks similar things, but its exact wording was not read, so the Google side is only a pointer.
These are prompts for the questionnaires, not answers: only you know what the app really does.
"""
from __future__ import annotations

from .discover import Project

TOPICS = [
    {"topic": "Unrestricted Web Access", "apple": True,
     "pattern": r"WKWebView|SFSafariViewController|webview_flutter|react-native-webview|flutter_inappwebview|"
                r"@capacitor/browser|InAppBrowser|expo-web-browser|android\.webkit\.WebView|CustomTabsIntent",
     "ask": "Can users navigate to any web page or freely browse the web inside the app?"},
    {"topic": "User-Generated Content", "apple": True,
     "pattern": r"stream-chat|sendbird|GiftedChat|gifted-chat|flutter_chat_ui|dash_chat|createComment|postComment|"
                r"CommentList|react-native-image-picker.*upload|ImageUploadPost",
     "ask": "Do users create content (videos, photos, text, audio) that is broadly distributed to other users?"},
    {"topic": "Messaging and Chat", "apple": True,
     "pattern": r"stream-chat|sendbird|GiftedChat|gifted-chat|flutter_chat_ui|dash_chat|pubnub|twilio-conversations|"
                r"MessageKit|ChatScreen",
     "ask": "Can users communicate directly with each other (text, voice or video chat, direct or group messages)?"},
    {"topic": "Shared Location", "apple": True,
     "pattern": r"CLLocationManager|FusedLocationProviderClient|geolocator|expo-location|react-native-geolocation|"
                r"@capacitor/geolocation|google_maps_flutter",
     "ask": "Does the app share real-world location with another person or group (live, background, precise or approximate)? "
            "The code only shows that location is used."},
    {"topic": "Advertising", "apple": True,
     "pattern": r"google_mobile_ads|play-services-ads|GoogleMobileAds|react-native-google-mobile-ads|AppLovin|applovin|"
                r"ironSource|ironsource|UnityAds|Vungle|Chartboost|AdColony|Audience ?Network",
     "ask": "Does the app show paid promotion (banner, video, playable, rich media or native ads)?"},
    {"topic": "Parental Controls / Age Assurance", "apple": True,
     "pattern": r"DeclaredAgeRange|AgeRangeService|age[_-]?gate|ageVerification|age_verification",
     "ask": "Does the app offer parental controls or confirm a person's age?"},
]


def rating_hints(project: Project) -> list[dict]:
    out = []
    for t in TOPICS:
        hit = project.find_signal(t["pattern"])
        if hit:
            out.append({"topic": t["topic"], "evidence": hit, "ask": t["ask"]})
    return out
