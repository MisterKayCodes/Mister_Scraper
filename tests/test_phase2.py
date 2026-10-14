from core import MessageCleaner, sanitize_filename, resolve_extension, parse_media_list

def test_brain():
    print("Testing Core (The Brain)...")

    # 1. Test Text Cleaner
    raw_tweet = (
        "Massive breakout on $SOL! Check out @CryptoBoss and join our VIP: "
        "https://t.me/fake_signals or visit https://scam.xyz for calls!"
    )
    signature = ">> Real VIP Channel: https://t.me/my_real_vip"
    
    cleaned = MessageCleaner.clean(raw_tweet, mode=1, signature=signature)
    print("\n--- Raw Tweet ---")
    print(raw_tweet)
    print("\n--- Cleaned & Branded Output ---")
    print(cleaned)

    assert "@CryptoBoss" not in cleaned, "Username was not stripped!"
    assert "https://t.me/fake_signals" not in cleaned, "Competitor TG link was not stripped!"
    assert "https://scam.xyz" not in cleaned, "Competitor URL was not stripped!"
    assert "https://t.me/my_real_vip" in cleaned, "Client signature was not appended!"
    print("\n[OK] MessageCleaner: PASS")

    # 2. Test Filename Sanitizer
    safe = sanitize_filename("Bitcoin Hits $100k! What's Next???")
    assert safe == "Bitcoin_Hits_100k_Whats_Next", f"Unexpected filename: {safe}"
    print(f"[OK] Sanitize Filename: PASS ({safe})")

    # 3. Test Extension Resolver
    ext_vid = resolve_extension("video/mp4", "https://video.twimg.com/test.mp4?tag=12")
    ext_img = resolve_extension("image/jpeg", "https://pbs.twimg.com/media/pic.jpg")
    assert ext_vid == "mp4"
    assert ext_img == "jpg"
    print(f"[OK] Resolve Extension: PASS (video->{ext_vid}, photo->{ext_img})")

    # 4. Test Media Parser
    payload = {
        "media_extended": [
            {"url": "https://video.twimg.com/vid.mp4", "type": "video"},
            {"url": "https://pbs.twimg.com/pic.jpg", "type": "image"}
        ]
    }
    parsed = parse_media_list(payload)
    assert len(parsed) == 2
    print(f"[OK] Parse Media List: PASS ({len(parsed)} items extracted)")

if __name__ == "__main__":
    test_brain()
