---
title: How do we validate the features extracted by the LLM?
date: 2026-03-19
author: Junyi Ji
description: We are sharing the methods we use to validate the LLM-extracted features.
---
This blog is under construction. The ready date is expected to be 2026-03-19.

The main concerns about LLM for feature extraction come from the trust.  We want to make sure the features extracted by LLM are useful for downstream tasks. 

## Method: Inter-rater agreement analysis
In general, inter-rater agreement analysis is a common method to evaluate the reliability of qualitative data. It measures the degree of agreement between two or more raters who independently classify items into categories. In this study, we use Cohen's kappa and Fleiss's kappa to evaluate the agreement between the features extracted by LLM and the features extracted by human annotators.

### Cohen's Kappa 
Cohen's kappa coefficient (Cohen's $\kappa$) is a statistic used to measure inter-rater reliability for qualitative or categorical data <a href="#ref-1">[1]</a>.

$$
\kappa = \frac{p_o - p_e}{1 - p_e}
$$

### Fleiss's Kappa 


**Our next blog will share our story on the manual validation process. Staying tuned!**


### References
<a id="ref-1"></a>[1] McHugh, M. L. (2012). Interrater reliability: the kappa statistic. Biochemia medica, 22(3), 276-282.