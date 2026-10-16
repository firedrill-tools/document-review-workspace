"use client";

import { CopilotChat, CopilotChatAssistantMessage, useAgent } from "@copilotkit/react-core/v2";
import { useEffect, useState, type ComponentProps } from "react";
import { defaultRehypePlugins } from "streamdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import rehypeKatex from "rehype-katex";

const markdownPlugins: ComponentProps<typeof CopilotChatAssistantMessage.MarkdownRenderer>["rehypePlugins"] = [
  defaultRehypePlugins.raw,
  [rehypeSanitize, { ...defaultSchema, attributes: { ...defaultSchema.attributes, code: [["className", /^language-./, "math-inline", "math-display"]] } }],
  [rehypeKatex, { trust: false, errorColor: "var(--color-muted-foreground)" }],
  defaultRehypePlugins.harden,
];

export function ReviewChat() {
  const { agent, isReady } = useAgent({ agentId: "review_agent" });
  const [error, setError] = useState("");
  useEffect(() => {
    const subscription = agent.subscribe({ onRunInitialized: () => { setError(""); } });
    return () => subscription.unsubscribe();
  }, [agent]);
  return <>
    {!isReady && <p role="status">Connecting to the review copilot…</p>}
    {error && <p className="error-banner" role="alert">{error}</p>}
    {isReady && <CopilotChat agentId="review_agent" className="chat"
      messageView={{ assistantMessage: { markdownRenderer: { rehypePlugins: markdownPlugins } } }}
      onError={() => setError("The review copilot could not complete this request. Inspect the document and try again.")} />}
  </>;
}
