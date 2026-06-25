# Evidence Schema

Use this schema for shopping-task data passed between the agent, scripts, and future app UI.

## Criteria

```json
{
  "task_name": "microwave-under-500-low-height",
  "category": "microwave oven",
  "report_version": "v1",
  "report_status": "初版",
  "report_candidate_limit": 3,
  "category_landscape_limits": {
    "subtypes": 4,
    "price_bands": 5,
    "optional_attributes": 6,
    "pain_points": 6
  },
  "summary": "Short report context.",
  "recommendation": "Final buying recommendation.",
  "blockers": ["JD required login before product list loaded."],
  "shopping_environment": {
    "observed_at": "2026-06-20T00:00:00Z",
    "overall_status": "ready",
    "active_backend": "taobao_cdp_direct",
    "next_step": "可以开始淘宝搜索；保持人类速度，并在报告中记录本次 doctor 状态。",
    "page_risk": []
  },
  "changes_from_previous": [],
  "category_landscape": {
    "subtypes": ["flatbed microwave", "turntable microwave"],
    "price_bands": ["entry 300-500 CNY", "mainstream 500-900 CNY"],
    "optional_attributes": ["capacity", "power", "height", "color", "control type"],
    "pain_points": ["too tall for shelf", "low power heats slowly", "black finish disliked"],
    "risk_signals": ["reseller with unclear warranty", "missing model/spec evidence"],
    "safe_signals": ["official/self-operated store", "exact model and dimensions verified"],
    "category_norms": ["compact models often trade capacity for lower height"],
    "decision_axes": ["low height vs capacity", "low price vs official seller"]
  },
  "second_round_questions": [
    "是否愿意为了更低高度接受更小容量？",
    "是否把官方/自营渠道作为硬要求？"
  ],
  "default_next_direction": "如果你没想法，下一版会优先补查差评/问大家，把候选收窄到2-3个，并按低风险优先重排。",
  "allowed_platforms": ["taobao", "tmall", "jd"],
  "store_requirements": ["official", "flagship", "self_operated"],
  "brand_policy": {
    "mode": "allow_list",
    "brands": ["Midea", "Galanz", "Panasonic", "Haier", "Toshiba"]
  },
  "hard_constraints": {
    "price_cny": {"max": 500},
    "power_w": {"min": 800},
    "height_cm": {"max": 27},
    "color": {"disallow": ["black", "黑色"]}
  },
  "soft_preferences": {
    "high_sales": true,
    "low_bad_reviews": true,
    "major_brand": true
  },
  "taobao_policy": {
    "minimum_store_trust_grade": "B",
    "require_selected_sku_evidence": true,
    "require_after_sales_evidence": true,
    "require_review_probe": true
  }
}
```

## Candidate

```json
{
  "id": "jd-123456",
  "title": "Midea microwave oven 20L",
  "brand": "Midea",
  "model": "M1-L213B",
  "platform": "jd",
  "store_name": "Midea JD self-operated flagship store",
  "store_type": "self_operated",
  "url": "https://item.jd.com/example.html",
  "canonical_url": "https://item.jd.com/example.html",
  "source_url": "https://search.jd.com/Search?keyword=example",
  "review_probe_url": "https://item.jd.com/example.html#comment",
  "image_url": "https://example.com/product.jpg",
  "screenshot_path": "work/shopping-captures/jd-123456.png",
  "source_platform": "jd",
  "purchase_platform_verified": true,
  "purchase_note": "Verified in JD self-operated flagship store.",
  "selected_sku": {
    "label": "20L white 800W standard version",
    "model": "M1-L213B",
    "color": "white",
    "price_cny": 399,
    "verified": true
  },
  "store_trust": {
    "grade": "A",
    "signals": ["self-operated", "flagship"],
    "rationale": "Brand self-operated flagship listing."
  },
  "price_cny": 399,
  "sales_text": "10万+评价",
  "review_count": 100000,
  "bad_review_count": 300,
  "bad_review_rate": 0.003,
  "after_sales": {
    "seven_day_no_reason": true,
    "return_freight_support": true,
    "warranty_text": "1 year warranty",
    "invoice_support": true,
    "installation_included": null,
    "notes": "Visible on product page."
  },
  "reviews": {
    "negative_review_checked": true,
    "follow_up_review_checked": true,
    "qna_checked": true,
    "severe_negative_themes": [],
    "medium_negative_themes": ["isolated packaging damage"],
    "mild_negative_themes": ["delivery delay"],
    "summary": "No recurring severe product or seller-risk theme found."
  },
  "specs": {
    "power_w": 800,
    "height_cm": 25.9,
    "color": "white",
    "capacity_l": 20,
    "dimensions_text": "440 x 358 x 259 mm"
  },
  "evidence": [
    {
      "field": "height_cm",
      "value": "259 mm",
      "source_url": "https://item.jd.com/example.html",
      "observed_at": "2026-06-18T00:00:00Z",
      "confidence": "high"
    }
  ]
}
```

## Evaluation Status

- `pass`: Known evidence satisfies every hard constraint and required purchase-channel checks.
- `needs_review`: No known hard constraint fails, but at least one hard constraint lacks enough evidence.
- `fail`: At least one known hard constraint fails.

## Evidence Rules

- Keep raw text in `evidence.value` when a field was parsed from a page.
- Use numeric normalized fields for filtering, such as `height_cm` or `power_w`.
- Put platform-specific labels in `store_type` only after verifying them. Use `unknown` otherwise.
- Do not infer store authenticity from title alone.
- Do not infer color from a promotional image unless a product option or spec confirms it.
- Use `selected_sku` for the currently selected buyable option. Title-level claims are not enough for Taobao/Tmall recommendations.
- Treat `url` and `image_url`/`screenshot_path` as product identity fields. They should be captured for every top candidate and rendered first in each candidate section, before pros, cons, scores, or evidence details.
- For Taobao/Tmall candidates, preserve URL roles instead of overwriting them: use `url` for the link the user should open to buy, `canonical_url` for a cleaned stable item identity when useful, `source_url` for the original search-result or marketplace URL used to collect evidence, and `review_probe_url` for the exact URL used to inspect reviews/follow-up reviews/`问大家`.
- Do not replace a Taobao/Tmall `source_url` with a simplified `detail.tmall.com/item.htm?id=...` or `item.taobao.com/item.htm?id=...` URL before review probing. Simplified item URLs can hide review modules. If review markers are missing on a simplified URL, retry with `source_url` or `review_probe_url` before recording review evidence as unavailable.
- For multi-material listings, record the exact `selected_sku.label` and material evidence for that SKU. Do not reject a whole listing or brand because another SKU in the same link uses an unwanted material.
- Use `store_trust.grade` with A/B/C/D/unknown. Derive it from visible store type, platform badges, store name, and authenticity signals; do not infer A-grade trust from brand words in the product title.
- Use `after_sales` for visible purchase protections and service terms. Use `null` when a term is not relevant, and omit or leave `unknown` only when it was not checked.
- Use `reviews` to capture whether negative reviews, follow-up reviews, and Q&A were checked. Severe themes should prevent a recommendation.
- For Taobao/Tmall top candidates, review probing is mandatory. Do not set `taobao_policy.require_review_probe` to `false` to bypass missing `negative_review_checked`, `follow_up_review_checked`, or `qna_checked`. The evaluator treats Taobao/Tmall review checks as required unless an explicit `allow_skip_taobao_review_probe: true` escape hatch is present for a user-approved quick scan.
- Keep `source_platform` separate from `platform` when an official brand site is only used as a spec evidence source.
- Use `purchase_platform_verified: false` when the product looks suitable but the required marketplace listing was blocked by login, captcha, risk control, or unavailable pages.
- Use `shopping_environment` to store the latest `shopping_doctor.py --json` summary for Taobao/Tmall work. Keep only durable status fields in reports or app data: `overall_status`, `active_backend`, `next_step`, and meaningful `page_risk`; never store cookies, profile paths containing account state, passwords, or raw browser process commands.
- Use `report_version`, `report_status`, and `changes_from_previous` to keep report iterations traceable. Use `report_status` values such as `初版`, `修订版`, `最终决策`, or `被阻塞`.
- Use `report_candidate_limit` to keep the visual report compact. Default to 3 candidates unless the user explicitly asks for a broader comparison.
- Use `category_landscape` as a market map, not a slogan list. Fill enough observed Taobao/Tmall facts to explain the category's branches, price bands, decision attributes, pain points, safe signals, norms, and tradeoffs. The renderer keeps each field bounded, so do not underfill important fields merely to stay short.
- Use `category_landscape_limits` only when a category genuinely needs more or fewer visible items for a field. Defaults are intentionally higher for price bands, optional attributes, and pain points than for shorter fields.
- Use `second_round_questions` and `default_next_direction` for the post-report chat delivery, not for the report body. The report should contain durable evidence; the chat should contain collaboration controls and next-step questions.
- Use `default_next_direction` for the next version plan shown in chat delivery. It should be specific to the latest evidence, not a generic "continue researching" sentence.
