import {
  ArrowDown, ArrowUp, CheckCircle, Clock, EyeSlash, Flask, HourglassLow, Lightbulb, MinusCircle, PencilSimpleLine,
  Prohibit, Question, Ruler, Scales, WarningCircle, XCircle, type Icon,
} from "@phosphor-icons/react";

// Every status word has one icon, everywhere it appears. Colour is kept for the few states that need someone.
export const STATUS_ICONS: Record<string, Icon> = {
  // evidence verdicts
  "Clearly higher": ArrowUp, "Clearly lower": ArrowDown, "Not clear": Scales, "Too few to tell": HourglassLow,
  "Explained by size": Ruler, "Hypothesis": Question,
  // profile versions, plans, proposals
  "Published": CheckCircle, "Draft": PencilSimpleLine, "Retired": MinusCircle, "Active": CheckCircle,
  "Open": Lightbulb, "Made a draft": PencilSimpleLine, "Dismissed": XCircle,
  // tests
  "Running": Flask, "Read": CheckCircle, "Stopped": MinusCircle, "Needs more accounts": HourglassLow,
  "Clear difference": ArrowUp, "No clear difference": Scales, "Held back": EyeSlash, "Worked": CheckCircle,
  // sources and capacity
  "On time": CheckCircle, "Missed its run": WarningCircle, "Over capacity": WarningCircle, "Within hours": CheckCircle,
  "Not judged": Question, "Excluded": Prohibit, "Withheld": EyeSlash, "Waiting": Clock,
};
