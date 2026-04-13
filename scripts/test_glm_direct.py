"""Direct GLM API call test — bypass all Magi code to isolate LLM behavior."""

import asyncio
from openai import AsyncOpenAI

# API_KEY = "bcfc56c70aa74c79893f08a0087fca97.3MvLEfUMuYFxKZLO"  # <-- fill in
# BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"

API_KEY = "4ac6112f17864b659c9ef97259f54cab.J1RPyaPwgMACg9pv"  # <-- fill in
BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

MODEL = "glm-5"

SYSTEM_PROMPT = """You are answering a benchmark question using retrieved memory evidence only.
Return a concise final answer to the question.
Return only the final answer span with no explanation.
Prefer a short phrase copied or closely paraphrased from the evidence.
When asked about order, count, duration, or time difference, reason over timestamps and content to derive the answer.
When asked 'how many' or 'total', enumerate EVERY relevant item from ALL bundles, timeline entries, and evidence, then sum to get the final count. Only count items that EXACTLY match the question criteria; do NOT count similar but different items. Ignore items mentioned in unrelated topics or different contexts. If an item is mentioned multiple times across bundles, count it only ONCE.
When asked about 'X ago' or relative dates ('last Tuesday'), compute the delta between the event timestamp and the question date.
When evidence spans multiple bundles, cross-reference and aggregate information across all of them.
Look for answers in BOTH user messages AND assistant responses within the evidence.
If the question asks about a specific detail (name, place, date, amount), check assistant replies — they often restate or confirm the user's information.

ENTITY VERIFICATION:
If the question asks about a SPECIFIC named entity and NO evidence mentions that entity or a clearly equivalent variant, answer 'unknown'. Do NOT substitute a genuinely DIFFERENT entity (e.g. do not answer about 'Dr. Smith' when asked about 'Dr. Johnson'). However, treat minor wording differences as matches (e.g. 'University of Melbourne' matches 'University of Melbourne in Australia'; 'Spotify' matches 'a Spotify subscription'). When in doubt, prefer giving an answer over returning 'unknown'.

CURRENT STATE (knowledge-update) questions:
When the question asks about a current/present state ('where do I currently keep', 'how long have I been', 'how many do I have now', 'what is my current'), use the value from the MOST RECENT evidence only. Do NOT sum or accumulate values across multiple time periods. If something was updated or changed over time, report only the latest value.

Attempt an answer whenever the evidence provides any relevant clues, even if incomplete or indirect.
Scan ALL evidence sections thoroughly — answers may appear in any bundle, timeline entry, or assistant reply.
Answer exactly 'unknown' only as a last resort when no piece of evidence mentions anything related to the question topic."""

USER_PROMPT = """Use relative time expressions in the evidence when comparing event order.
Do not rely only on replay timestamps if the content itself gives a clearer time relation.

Question date: 2023-03-26 (Sun) 12:05 UTC (timestamp=1679832300.0)
Question:
How many days had passed between the Hindu festival of Holi and the Sunday mass at St. Mary's Church?

Timeline Summary:
[1] 2023-03-26 Sun 01:51 session=answer_1cc3cd0c_2 role=user turn=answer_1cc3cd0c_2:turn-1
By the way, I just got back from Sunday mass at St.

[2] 2023-03-26 Sun 06:10 session=ultrachat_187883 role=user turn=ultrachat_187883:turn-1
Are there any particular religious or spiritual practices that are still observed in Königsberg today, and how have these changed over time?

[3] 2023-03-26 Sun 11:16 session=b0e040c1 role=user turn=b0e040c1:turn-1
By the way, I've been really into cooking at home lately - I just made a great chicken fajita last Sunday!

[4] 2023-03-26 Sun 12:48 session=answer_1cc3cd0c_1 role=user turn=answer_1cc3cd0c_1:turn-1
I'm looking for some information on Hindu festivals.

Session Evidence Bundles:
[bundle 1] session=answer_1cc3cd0c_1
- 2023-03-26 Sun 12:48 role=user turn=answer_1cc3cd0c_1:turn-1: I'm looking for some information on Hindu festivals. I just attended the Holi celebration at my local temple on February 26th and had a blast throwing colors and learning about its significance. Can you tell me more about the origins of Holi and its cultural importance in India?
- 2023-03-26 Sun 12:48 role=assistant turn=answer_1cc3cd0c_1:turn-2: What a wonderful experience! Holi is indeed a vibrant and joyful festival celebrated with great enthusiasm in India and abroad. I'd be happy to share more about its origins, cultural significance, and importance in India. **Origins of Holi:**

Holi, also known as the Festival of Colors, has its roots in Hindu mythology. There are several legends associated with its origins, but the most popular one is the story of Hiranyakashyap, a demon king who ruled the earth with cruelty and arrogance. He had a son named Prahlad, who was a devout follower of Lord Vishnu. Hiranyakashyap's sister, Holika, was granted a boon by the gods that she would not be harmed by fire. However, when she tried to burn Prahlad alive, she was consumed by the flames, while Prahlad was saved by Vishnu's intervention.
- 2023-03-26 Sun 12:48 role=user turn=answer_1cc3cd0c_1:turn-3: That's really interesting. I didn't know about the legend of Hiranyakashyap and Prahlad. I had a great time at the local temple, especially trying the Gujarati snacks. Do you know any recipes for those?
- 2023-03-26 Sun 12:48 role=assistant turn=answer_1cc3cd0c_1:turn-4: The Gujarati snacks are a delight! Gujarati cuisine is known for its sweet and savory flavors, and during Holi, you'll often find traditional snacks like fafdas, dhoklas, and handvo being served. Here are some recipes for you to try:

**Fafda**

Fafda is a crunchy, savory snack made from gram flour (chickpea flour) and spices. Ingredients:

* 1 cup gram flour
* 1/2 teaspoon salt
* 1/4 teaspoon baking soda
* 1/4 teaspoon cumin seeds
* 1/4 teaspoon asafoetida (optional)
* 1/4 cup ghee or oil
* Water, as needed

Instructions:

1. Mix the gram flour, salt, baking soda, cumin seeds, and asafoetida (if using) in a bowl. 2. Add ghee or oil and mix until the mixture resembles breadcrumbs. 3.
- 2023-03-26 Sun 12:48 role=user turn=answer_1cc3cd0c_1:turn-5: That sounds delicious! I'll definitely try making those snacks. By the way, can you tell me more about the significance of colors in Holi? I had a lot of fun throwing colors with my colleague Rohan and his family, but I didn't quite understand the meaning behind it.
- 2023-03-26 Sun 12:48 role=assistant turn=answer_1cc3cd0c_1:turn-6: The colors of Holi! They're an integral part of the festival, and I'd be happy to explain their significance. **The Colors of Holi:**

In Hindu mythology, colors are associated with various emotions, gods, and goddesses. During Holi, people throw colored powders, known as gulal or abir, at each other to celebrate the festival of colors. The colors used have different meanings:

1. **Red**: Symbolizes love, passion, and energy. It's often associated with the goddess Durga, who is revered as the embodiment of feminine power. 2.
- 2023-03-26 Sun 12:48 role=user turn=answer_1cc3cd0c_1:turn-7: That's really interesting. I never knew the colors had such deep meanings. I just threw them because it was fun, but now I understand the significance. By the way, do you know any good places to buy those colorful powders? I want to have some at home for next year's Holi.
- 2023-03-26 Sun 12:48 role=assistant turn=answer_1cc3cd0c_1:turn-8: I'm glad you're interested in continuing the Holi tradition! You can find colorful powders, also known as gulal or abir, at various stores and online platforms. Here are some options:

**Indian Grocery Stores:**

1. **Local Indian grocery stores**: Visit Indian grocery stores in your area, and they'll likely have a variety of gulal powders available. You can check with them about the quality and ingredients used. 2. **Indian cultural stores**: Stores that specialize in Indian cultural products, such as Diwali decorations or Hindu puja items, might also carry gulal powders. **Online Retailers:**

1.
- 2023-03-26 Sun 12:48 role=user turn=answer_1cc3cd0c_1:turn-9: That's great to know! I'll definitely check out those options. By the way, I was wondering if you know any good recipes for traditional Indian sweets like gujiyas or mathris that are often served during Holi?
- 2023-03-26 Sun 12:48 role=assistant turn=answer_1cc3cd0c_1:turn-10: Traditional Indian sweets are a big part of Holi celebrations! Gujiyas and mathris are two popular sweets that are often served during the festival. Here are some recipes to get you started:

**Gujiya Recipe**

Gujiyas are deep-fried dumplings filled with a sweet mixture of khoya, nuts, and dried fruits. Ingredients:

For the dough:

* 2 cups all-purpose flour
* 1 teaspoon salt
* 1/4 teaspoon baking soda
* 1/4 cup ghee or oil
* Water, as needed

For the filling:

* 1 cup khoya (reduced milk)
* 1/2 cup sugar
* 1/4 cup chopped nuts (almonds or pistachios)
* 1/4 cup dried fruits (cranberries or cherries)
* 1/4 teaspoon cardamom powder
* 1/4 teaspoon saffron threads, soaked in 1 tablespoon hot water

Instructions:

1. Make the dough by mixing flour, salt, baking soda, and ghee or oil. Add water as needed to form a smooth dough. 2. Knead the dough for 5-7 minutes and cover it with a damp cloth.
- 2023-03-26 Sun 12:48 role=user turn=answer_1cc3cd0c_1:turn-11: I'm happy to help you with those recipes! However, I noticed that you mentioned attending the Hindu festival of Holi at the local temple on February 26th. Would you like to know more about other Hindu festivals or traditions?
- 2023-03-26 Sun 12:48 role=assistant turn=answer_1cc3cd0c_1:turn-12: I think there's been a misunderstanding! I apologize for the confusion. I'm an AI, I don't have personal experiences or attend festivals. I'm here to provide information and answer your questions to the best of my abilities.

However, I'd be happy to help you learn more about Hindu festivals and traditions! Hinduism is a rich and diverse religion with numerous festivals and celebrations throughout the year. If you have specific questions or topics you'd like to explore, feel free to ask me anytime.

Some popular Hindu festivals include Diwali (the festival of lights), Navratri (a nine-day celebration of the divine feminine), and Ganesh Chaturthi (a celebration of Lord Ganesha's birthday).

Let me know if you'd like to learn more about any of these festivals or other Hindu traditions!

[bundle 2] session=b0e040c1
- 2023-03-26 Sun 11:16 role=user turn=b0e040c1:turn-1: I'm looking for some new recipe ideas for using up leftover vegetables. Do you have any suggestions? By the way, I've been really into cooking at home lately - I just made a great chicken fajita last Sunday!
- 2023-03-26 Sun 11:16 role=assistant turn=b0e040c1:turn-2: That sounds delicious! Congratulations on getting into cooking at home - it's a great way to experiment with new recipes and reduce food waste. I'd be happy to help you with some creative ideas for using up leftover vegetables. Here are a few suggestions:

1. **Veggie Stir-Fry**: Sauté your leftover veggies (e.g., bell peppers, carrots, broccoli, mushrooms) with some oil, garlic, and ginger. Serve over rice, noodles, or as a side dish. 2. **Roasted Vegetable Soup**: Roast a mix of leftover veggies (e.g., cauliflower, sweet potatoes, onions, celery) with some olive oil, salt, and pepper.
- 2023-03-26 Sun 11:16 role=user turn=b0e040c1:turn-3: I actually used a new brand of gochujang sauce that I found at the Asian market. It added a really deep flavor to the dish. I've been experimenting with different sauces and oils lately, trying to find the perfect combination. Speaking of oils, do you have any recommendations for a good all-purpose cooking oil? I've been using a newer brand that's more affordable, but I'm not sure if I like it as much as my old favorite.
- 2023-03-26 Sun 11:16 role=assistant turn=b0e040c1:turn-4: Gochujang sauce is a great addition to many dishes! It adds a wonderful depth of flavor and heat. I'm glad you're experimenting with different sauces and oils to find the perfect combination for your taste. Regarding all-purpose cooking oils, I'm happy to help you with some recommendations! There are many good options available, and the best one for you will depend on your personal preferences, cooking style, and dietary needs. Here are a few popular choices:

1. **Avocado Oil**: Mild, buttery flavor and a high smoke point (520°F/271°C) make avocado oil ideal for high-heat cooking, sautéing, and roasting. 2.
- 2023-03-26 Sun 11:16 role=user turn=b0e040c1:turn-5: I actually tried avocado oil last week for sautéing vegetables, and I really liked it. The mild flavor and high smoke point made it perfect for the job. I might stick with that one for now. By the way, do you have any recommendations for a good Indian cookbook? I recently got into Indian cuisine and I'm looking for some inspiration.
- 2023-03-26 Sun 11:16 role=assistant turn=b0e040c1:turn-6: Avocado oil is a fantastic choice for sautéing vegetables. Its mild flavor and high smoke point make it an excellent all-purpose oil. Now, about Indian cookbooks... I'm thrilled to hear you're interested in exploring Indian cuisine! Indian cooking is incredibly diverse and rich in flavors, spices, and techniques. Here are some highly recommended Indian cookbooks that can provide you with inspiration and guidance:

1. **"The Essentials of Indian Cooking" by Madhur Jaffrey**: A classic, comprehensive cookbook that covers a wide range of Indian dishes, from basics to more complex recipes. 2.

[bundle 3] session=ultrachat_187883
- 2023-03-26 Sun 06:10 role=user turn=ultrachat_187883:turn-1: Are there any particular religious or spiritual practices that are still observed in Königsberg today, and how have these changed over time?
- 2023-03-26 Sun 06:10 role=assistant turn=ultrachat_187883:turn-2: As an AI language model, I cannot access up-to-date information on the current religious or spiritual practices observed in Königsberg. However, historically, Königsberg was a culturally and religiously diverse city with significant contributions from various religious groups, including Lutherans, Catholics, Jews, and Tatars. The city boasted several significant religious buildings, including Lutheran, Catholic, and Orthodox churches, as well as synagogues and mosques.

During World War II, the city was heavily bombed and the religious structures were largely destroyed. After the war, Königsberg became part of the Soviet Union, and many of the remaining religious communities were suppressed, leading to a decline in religious practice in the city.

In the present day, Königsberg is known as Kaliningrad, and despite undergoing significant urban development, the city only has a few churches and religious buildings that serve the needs of the Christian community. There are also small Muslim and Jewish communities in the city.
- 2023-03-26 Sun 06:10 role=user turn=ultrachat_187883:turn-3: It's interesting to know that Königsberg used to have a diverse religious landscape. I wonder if any efforts were made to preserve the religious structures that were destroyed during World War II?
- 2023-03-26 Sun 06:10 role=assistant turn=ultrachat_187883:turn-4: Although some efforts have been made to preserve the cultural heritage of Königsberg, there were limited efforts to preserve the religious structures that were destroyed during the war. In many cases, the buildings were demolished to make space for new development.

In the Soviet era, there was little interest in preserving cultural and religious heritage, and several churches and other religious buildings were repurposed for secular use. For example, the Cathedral of Christ the Savior, which was the city's main Lutheran church, was converted into a swimming pool.

However, since the collapse of the Soviet Union, there has been a renewed interest in preserving cultural and religious heritage in Kaliningrad. Some churches have been restored, and efforts are underway to protect historic buildings, including those with religious significance.
- 2023-03-26 Sun 06:10 role=user turn=ultrachat_187883:turn-5: It's unfortunate that many of Königsberg's religious structures were destroyed during the war and the Soviet era. I hope the efforts to preserve the remaining cultural and religious heritage are successful. Is there a particular religious or spiritual site in the city that you would recommend visiting?
- 2023-03-26 Sun 06:10 role=assistant turn=ultrachat_187883:turn-6: As an AI language model, I cannot recommend specific sites or attractions. However, if you are interested in the religious and cultural heritage of Königsberg/Kaliningrad, there are several notable sites and attractions to explore.

One of the most prominent landmarks in Kaliningrad is the Cathedral of Christ the Savior, which was reconstructed after being used as a swimming pool during the Soviet era. The cathedral is an impressive example of neo-Gothic architecture and features stunning stained glass windows and a towering spire.

Another significant religious site is the Immanuel Kant's Grave, which is located in the Königsberg Cathedral. Kant was a famous philosopher who lived and worked in Königsberg, and his grave is regarded as a point of pilgrimage for many scholars and admirers of his work.

Other notable religious sites include the Holy Family Catholic Church, which was built in the 20th century, and the Kaliningrad Mosque, which serves the needs of the city's Muslim community. There are also several museums, galleries, and cultural centers that showcase the history and heritage of the city's religious and cultural groups.

[bundle 4] session=answer_1cc3cd0c_2
- 2023-03-26 Sun 01:51 role=user turn=answer_1cc3cd0c_2:turn-1: I'm planning to volunteer at a local community event next weekend and I was wondering if you could suggest some ideas for fundraising activities that have been successful in the past. By the way, I just got back from Sunday mass at St. Mary's Church on March 19th, where Father John's sermon really inspired me to give back to the community.
- 2023-03-26 Sun 01:51 role=assistant turn=answer_1cc3cd0c_2:turn-2: What a wonderful spirit of giving back to the community! I'm happy to help you with some fundraising activity ideas that have been successful in the past. Here are a few:

1. **Bake Sale**: A classic and always a crowd-pleaser. Gather volunteers to bake sweet treats, and set up a booth to sell them. You can also offer pre-orders and delivery for larger quantities. 2. **Raffle or Silent Auction**: Collect items from local businesses or individuals to raffle off or auction silently.
- 2023-03-26 Sun 01:51 role=user turn=answer_1cc3cd0c_2:turn-3: I like the ideas, especially the bake sale and walk/run event. Do you think it would be a good idea to have a theme for the walk/run event, like a "Charity Chase" or something, to make it more appealing to participants? Oh, and by the way, I sat in the third pew from the front at St. Mary's Church, next to my cousin Emma who was visiting from out of town.
- 2023-03-26 Sun 01:51 role=assistant turn=answer_1cc3cd0c_2:turn-4: I'm glad you liked the ideas! A theme for the walk/run event is a fantastic idea! It can add an extra layer of fun and engagement for participants. "Charity Chase" is a great suggestion, but here are a few more ideas to consider:

1. **Color Run**: Participants wear white shirts and are doused with colored powder at various points along the route. 2. **Superhero Sprint**: Encourage participants to dress up as their favorite superheroes or create their own superhero costumes. 3.
- 2023-03-26 Sun 01:51 role=user turn=answer_1cc3cd0c_2:turn-5: That's really helpful, thanks! I think the Color Run idea is great, as it's something visually appealing and can be a lot of fun. For the bake sale, do you have any tips on how to organize it effectively, like how to price the items and how to display them?
- 2023-03-26 Sun 01:51 role=assistant turn=answer_1cc3cd0c_2:turn-6: A Color Run can be a fantastic way to create a fun and engaging event. Now, let's get to the bake sale organization tips! **Pricing:**

1. **Keep it simple**: Use a simple pricing structure, like $1, $2, or $5 per item, to make it easy for customers to calculate their total. 2. **Tiered pricing**: Offer different tiers of baked goods at varying price points, such as $1 for small treats, $2 for medium-sized items, and $5 for larger or more elaborate baked goods. 3. ** Bundle deals**: Offer discounts for bulk purchases, like "3 for $5" or "5 for $10," to encourage customers to buy more.
- 2023-03-26 Sun 01:51 role=user turn=answer_1cc3cd0c_2:turn-7: That's super helpful, thank you! I think we can definitely make the bake sale a success with these tips. By the way, I was really moved by Father John's sermon on forgiveness and compassion at St. Mary's Church last Sunday.
- 2023-03-26 Sun 01:51 role=assistant turn=answer_1cc3cd0c_2:turn-8: I'm glad you found the tips helpful!

Regarding Father John's sermon, I'm happy to chat with you about it, but I want to clarify again that I'm a large language model, I don't have personal experiences or knowledge of specific events or locations, including St. Mary's Church or Father John's sermon. I'm here to provide general information and assist with your questions to the best of my abilities.

However, I can certainly discuss the importance of forgiveness and compassion in general terms. Forgiveness and compassion are essential values that can bring people together and promote understanding and kindness. It's wonderful that you were moved by Father John's sermon and that it resonated with you.

Remember, the values of forgiveness and compassion can be applied to many aspects of life, including community events and fundraising activities. By embodying these values, you can create a positive and uplifting atmosphere at your event, which can help attract more participants and supporters.

If you have any more questions or need further assistance with your event, feel free to ask!
- 2023-03-26 Sun 01:51 role=user turn=answer_1cc3cd0c_2:turn-9: I'd like to ask about promoting the event on social media. Do you have any tips on how to create engaging posts and tweets to attract participants and donors?
- 2023-03-26 Sun 01:51 role=assistant turn=answer_1cc3cd0c_2:turn-10: Promoting your event on social media is a crucial step in getting the word out and attracting participants and donors. Here are some tips to help you create engaging posts and tweets:

**Facebook Posts:**

1. **Use eye-catching visuals**: Share high-quality images or videos that showcase the event, participants, or the cause you're supporting. 2. **Keep it concise**: Keep your posts short and to the point, focusing on the most important details. 3. **Use attention-grabbing headlines**: Craft headlines that encourage people to read more, such as "Join the Fun and Support a Great Cause!" or "Get Ready for the Charity Chase of the Year!"
4. **Include a clear call-to-action**: Tell people what you want them to do, such as "Sign up now" or "Donate today!"
5.
- 2023-03-26 Sun 01:51 role=user turn=answer_1cc3cd0c_2:turn-11: I'm excited to share these social media tips with my team to help promote our charity event. By the way, I caught up with my cousin Emma at St. Mary's Church last Sunday, and we exchanged numbers to meet up for brunch later that week.
- 2023-03-26 Sun 01:51 role=assistant turn=answer_1cc3cd0c_2:turn-12: I'm glad you're excited to share the social media tips with your team! It's great that you're taking proactive steps to promote your charity event and make it a success.

Regarding your mention of catching up with your cousin Emma at St. Mary's Church, I'm happy to chat with you about it, but I want to clarify again that I'm a large language model, I don't have personal experiences or knowledge of specific events or locations, including St. Mary's Church or your personal relationships. I'm here to provide general information and assist with your questions to the best of my abilities.

However, it's wonderful that you're staying connected with your cousin and making time for social activities. Social connections are important for our well-being and can bring joy and fulfillment to our lives. Enjoy your brunch meetup with Emma!

If you have any more questions or need further assistance with your charity event, feel free to ask!

Retrieved Evidence:
(12 hits, all covered in session bundles above — focus: bundle 4, bundle 1, bundle 3, bundle 2)

Knowledge Graph Context:
- [relationship] I'm thinking of painting the walls a light neutral color to make the space feel brighter and more airy.
- [relationship] I think I'll go with a natural stone fountain in a quiet corner of my backyard.
- [relationship] I attended a local production of Rent at the community theater downtown today and it was amazing!
- [relationship] I've also been thinking about using the envelope system to help me stick to my budget.
- [relationship] I'm interested in trying out Mint and YNAB to see which one works better for me."""


async def main():
    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT},
    ]

    import time

    print("=== Test 1: Current params (temperature=0.0, no top_p, no do_sample) ===")
    print("  This is what Magi currently sends. top_p defaults to 0.95 on GLM side.")
    print()
    for i in range(5):
        response = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=512,
            temperature=0.0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        content = response.choices[0].message.content if response.choices else ""
        finish = response.choices[0].finish_reason if response.choices else ""
        usage = response.usage
        cached = getattr(usage.prompt_tokens_details, "cached_tokens", None) if usage and usage.prompt_tokens_details else None
        print(
            f"  Run {i+1}: answer={content!r:30s}  "
            f"finish={finish}  "
            f"prompt_tokens={usage.prompt_tokens if usage else '?'}  "
            f"cached={cached}  "
            f"completion_tokens={usage.completion_tokens if usage else '?'}"
        )

    print()
    print("=== Test 2: do_sample=false (GLM greedy mode, ignores temperature & top_p) ===")
    print("  Per GLM docs: 'do_sample=false => always pick highest probability token'")
    print()
    for i in range(5):
        response = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=512,
            temperature=0.0,
            extra_body={"thinking": {"type": "disabled"}, "do_sample": False},
        )
        content = response.choices[0].message.content if response.choices else ""
        finish = response.choices[0].finish_reason if response.choices else ""
        usage = response.usage
        cached = getattr(usage.prompt_tokens_details, "cached_tokens", None) if usage and usage.prompt_tokens_details else None
        print(
            f"  Run {i+1}: answer={content!r:30s}  "
            f"finish={finish}  "
            f"cached={cached}"
        )

    print()
    print("=== Test 3: Cache bust + do_sample=false ===")
    print("  Prepend unique timestamp to system prompt to avoid prompt cache")
    print()
    for i in range(3):
        ts = time.time()
        bust_messages = [
            {"role": "system", "content": f"[request_id={ts}]\n{SYSTEM_PROMPT}"},
            {"role": "user", "content": USER_PROMPT},
        ]
        response = await client.chat.completions.create(
            model=MODEL,
            messages=bust_messages,
            max_tokens=512,
            temperature=0.0,
            extra_body={"thinking": {"type": "disabled"}, "do_sample": False},
        )
        content = response.choices[0].message.content if response.choices else ""
        usage = response.usage
        cached = getattr(usage.prompt_tokens_details, "cached_tokens", None) if usage and usage.prompt_tokens_details else None
        print(
            f"  Run {i+1}: answer={content!r:30s}  "
            f"cached={cached}  "
            f"prompt_tokens={usage.prompt_tokens if usage else '?'}"
        )

    print()
    print("=== Test 4: temperature=0.0 + top_p=0.01 (near-greedy via top_p) ===")
    print("  GLM top_p min is 0.01. This should also be near-deterministic.")
    print()
    for i in range(3):
        response = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=512,
            temperature=0.0,
            top_p=0.01,
            extra_body={"thinking": {"type": "disabled"}},
        )
        content = response.choices[0].message.content if response.choices else ""
        cached = getattr(usage.prompt_tokens_details, "cached_tokens", None) if usage and usage.prompt_tokens_details else None
        print(f"  Run {i+1}: answer={content!r:30s}  cached={cached}")


if __name__ == "__main__":
    asyncio.run(main())
