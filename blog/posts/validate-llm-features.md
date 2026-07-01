---
title: How do we validate the features extracted by the LLM?
date: 2026-03-19
author: Junyi Ji
description: We are sharing the methods we use to validate the LLM-extracted features.
---
The main concerns about LLM for feature extraction come from the trust. We want to make sure the features extracted by LLM are useful for downstream tasks.

To build that trust, we built a Manual Validation Dataset (MVD) of 96 randomly selected papers. Each paper was independently labeled by two human experts (H1, H2) and by our LLM pipeline, on features such as whether the paper shares a public code repository (`is_code_publicly_available`). We then measured how well the three "raters" agree with each other. This blog walks through the two statistics we used, Cohen's kappa and Fleiss's kappa, with worked examples built from our own validation data. All numbers below are checked against the results table in the paper <a href="#ref-3">[3]</a>.

## Method: Inter-rater agreement analysis
In general, inter-rater agreement analysis is a common method to evaluate the reliability of qualitative data. It measures the degree of agreement between two or more raters who independently classify items into categories. In this study, we use Cohen's kappa and Fleiss's kappa to evaluate the agreement between the features extracted by LLM and the features extracted by human annotators.

### Cohen's Kappa
Cohen's kappa coefficient (Cohen's $\kappa$) is a statistic used to measure inter-rater reliability between **two** raters on categorical data <a href="#ref-1">[1]</a>.

$$
\kappa = \frac{p_o - p_e}{1 - p_e}
$$

Here $p_o$ is the observed proportion of items on which the two raters agree, and $p_e$ is the proportion of agreement we would expect by chance alone, given each rater's own tendency to use each category. For two raters and two categories (Yes/No), if rater 1 says "Yes" on a fraction $p_1$ of the $N$ items and rater 2 says "Yes" on a fraction $p_2$ of the items, then, under independence,

$$
p_e = p_1 p_2 + (1-p_1)(1-p_2).
$$

**Worked example.** In the MVD, for the feature `is_code_publicly_available`, H1 marked 8 of the 96 papers as sharing code, and H2 marked 5 of the 96 papers. We can reconstruct the 2×2 table behind these numbers that is consistent with the percentage agreement and Cohen's $\kappa$ we report for H1 vs. H2 in the paper:

| | H2: Yes | H2: No | Row total |
|---|---|---|---|
| **H1: Yes** | 5 | 3 | 8 |
| **H1: No** | 0 | 88 | 88 |
| **Column total** | 5 | 91 | 96 |

From this table:

$$
p_o = \frac{5+88}{96} = 0.969, \qquad p_e = \frac{8}{96}\cdot\frac{5}{96} + \frac{88}{96}\cdot\frac{91}{96} = 0.873
$$

$$
\kappa = \frac{0.969 - 0.873}{1 - 0.873} \approx 0.753
$$

This matches the Cohen's $\kappa$ (H1 vs. H2) of 0.753 reported for `is_code_publicly_available`, which the Landis & Koch scale <a href="#ref-2">[2]</a> classifies as **Substantial** agreement. Doing the same exercise for H1 vs. our LLM pipeline gives an even tighter table (7, 1, 0, 88), which works out to $\kappa \approx 0.928$, that is, the LLM agreed with H1 more consistently than H2 did.

### Fleiss's Kappa
Cohen's kappa only handles two raters. Since our study has three raters per paper (H1, H2, and the LLM), we use Fleiss's kappa <a href="#ref-4">[4]</a>, which generalizes the same idea to any number of raters and categories.

For $N$ subjects (papers), $n$ raters per subject, and $k$ categories, let $n_{ij}$ be the number of raters who assigned subject $i$ to category $j$. The observed agreement for subject $i$ is the fraction of rater *pairs* who agree on that subject:

$$
P_i = \frac{1}{n(n-1)}\sum_{j=1}^{k} n_{ij}\left(n_{ij}-1\right)
$$

Averaging over all subjects gives the overall observed agreement $\bar{P} = \frac{1}{N}\sum_i P_i$. The expected agreement by chance is computed from the overall proportion of assignments falling in each category, $p_j = \frac{1}{Nn}\sum_i n_{ij}$:

$$
\bar{P}\_e = \sum\_{j=1}^{k} p_j^2, \qquad \kappa = \frac{\bar{P} - \bar{P}\_e}{1 - \bar{P}\_e}
$$

**Worked example.** Extending the same feature (`is_code_publicly_available`) to all three raters, the 96 papers split into four groups by how many of the three raters said "Yes":

| Votes for "code available" (out of 3 raters) | Number of papers | $P_i$ |
|---|---|---|
| 3 (H1, H2, LLM all say Yes) | 5 | 1.000 |
| 2 (two of three say Yes) | 2 | 0.333 |
| 1 (one of three says Yes) | 1 | 0.333 |
| 0 (all three say No) | 88 | 1.000 |

$$
\bar{P} = \frac{5(1) + 2(0.333) + 1(0.333) + 88(1)}{96} = \frac{94}{96} \approx 0.979
$$

Across the $96 \times 3 = 288$ total ratings, 20 were "Yes" and 268 were "No," so $p_{\text{yes}} \approx 0.069$ and $p_{\text{no}} \approx 0.931$:

$$
\bar{P}_e = 0.069^2 + 0.931^2 \approx 0.871
$$

$$
\kappa = \frac{0.979 - 0.871}{1 - 0.871} \approx 0.839
$$

This matches the Fleiss's $\kappa$ (all three raters) of 0.839 reported in the paper for `is_code_publicly_available`, an **Almost Perfect** level of agreement.

### Interpreting the scores
We interpret both statistics using the Landis & Koch scale <a href="#ref-2">[2]</a>:

| Fleiss's / Cohen's $\kappa$ | Interpretation |
|---|---|
| 0.21 – 0.40 | Fair |
| 0.41 – 0.60 | Moderate |
| 0.61 – 0.80 | Substantial |
| 0.81 – 1.00 | Almost Perfect |

Repeating this analysis across the four validated features gives the following Fleiss's $\kappa$ values, reported in the paper <a href="#ref-3">[3]</a>:

| Feature | Fleiss's $\kappa$ | Interpretation |
|---|---|---|
| `is_code_publicly_available` | 0.839 | Almost Perfect |
| `is_data_cited` | 0.522 | Moderate |
| `is_quantitative_study` | 0.459 | Moderate |
| `is_data_repository_available` | 0.399 | Fair |

The most objective feature, whether code is publicly shared, has the highest agreement. Data-related features are more ambiguous, and importantly, the LLM's agreement with each human annotator tracked the human-human agreement on those same features, rather than falling behind it. That comparison is what gives us confidence that the LLM pipeline is a valid substitute for exhaustive manual annotation at scale.

**Our next blog will share our story on the manual validation process. Staying tuned!**

### References
<a id="ref-1"></a>[1] McHugh, M. L. (2012). Interrater reliability: the kappa statistic. Biochemia medica, 22(3), 276-282.

<a id="ref-2"></a>[2] Landis, J. R., & Koch, G. G. (1977). The measurement of observer agreement for categorical data. Biometrics, 33(1), 159-174.

<a id="ref-3"></a>[3] Ji, J., Lu, R., Belkessa, L., Wang, L., Varotto, S., Dong, Y., Saunier, N., Ameli, M., Macfarlane, G. S., Madadi, B., & Wu, C. (2026). Measuring the State of Open Science in Transportation Using Large Language Models.

<a id="ref-4"></a>[4] Fleiss, J. L. (1971). Measuring nominal scale agreement among many raters. Psychological Bulletin, 76(5), 378-382.