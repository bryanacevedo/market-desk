// What each status word means, shown on hover.
export const STATUS_MEANING: Record<string, string> = {
  "Clearly higher": "Wins more often than the rest, by more than chance.",
  "Clearly lower": "Wins less often than the rest, by more than chance.",
  "Not clear": "The difference could be chance.",
  "Too few to tell": "Fewer than 30 opportunities or 5 wins.",
  "Explained by size": "The difference goes away within each company size band.",
  "Hypothesis": "No evidence behind this rule yet.",
  "Not judged": "Less than 60% of the profile is known for this company.",
  "Needs more accounts": "Too few accounts to read a difference yet.",
};
