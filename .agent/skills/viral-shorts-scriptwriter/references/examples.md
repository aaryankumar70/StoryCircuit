# Examples

## Model script (passes the validator: 141 words, ~57 s at 2.6 wps)
Niche: cons_and_heists. Hook pattern: impossible_claim.

> In 1925, a con man sold the Eiffel Tower. Then he sold it again.
> Victor Lustig read a newspaper story about the tower's repair bills.
> He forged government letters and invited six scrap dealers to a Paris hotel.
> He claimed the city secretly wanted the tower torn down and sold for metal.
> One dealer, André Poisson, wanted the deal badly.
> Poisson paid the bribe and the full price, and Lustig vanished to Vienna.
> Poisson was too embarrassed to call the police. So Lustig came back and tried it again.
> Years later, in Chicago, he borrowed fifty thousand dollars from Al Capone.
> He locked it in a vault for two months, then returned every cent.
> Capone was so impressed he handed Lustig five thousand dollars.
> The man who sold the Eiffel Tower twice had even conned a gangster into paying for honesty.

Why it works: concrete hook; named people and numbers every sentence; each line adds a new fact; the second sale and the Capone turn escalate; last line echoes "sold the Eiffel Tower".
Verify facts again before publishing; use it as a style model, not as a topic to reuse blindly.

## Before / after (weak hook)
Before: "Have you ever wondered how a famous con man managed to fool so many people? Today we're diving into an incredible story."
After: "In 1925, a con man sold the Eiffel Tower. Then he sold it again."

## Before / after (weak ending)
Before: "This story serves as a reminder that trust can be dangerous. Follow for more amazing stories!"
After: "The man who sold the Eiffel Tower twice had even conned a gangster into paying for honesty."

## Before / after (padding)
Before: "He was a very clever man who was known for being good at tricking people, and he used his cleverness to come up with a plan."
After: "He forged government letters and invited six scrap dealers to a Paris hotel."
