# iOS app

Open Terminal on a Mac with Xcode, then:

    brew install xcodegen
    cd ios && xcodegen
    open FastOBD.xcodeproj

In Xcode: select the FastOBD target > Signing & Capabilities > pick your Apple ID team and change the
bundle identifier to something unique (for example com.yourname.fastobd). Plug in the iPhone, choose it
as the run destination, press Run. A free Apple ID works (the app lasts 7 days, then re-run).

Pair the OBDLink MX+ in iPhone Settings > Bluetooth first (press the Connect button on the adapter).
