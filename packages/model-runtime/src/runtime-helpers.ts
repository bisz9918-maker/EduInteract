import {
  type LanguageModel,
  type LanguageModelMiddleware,
  modelMessageSchema,
  tool,
  type ModelMessage,
  type OnStepFinishEvent,
  type ToolSet,
  wrapLanguageModel
} from "ai";

import type { Usage } from "@oah/api-contracts";
import type {
  GenerateModelInput,
  ModelStepPreparation,
  ModelStepResult,
  EngineToolSet
} from "@oah/engine-core";
import { AppError } from "@oah/engine-core";

function maybeToUrl(value: string): string | URL {
  const trimmed = value.trim();
  if (!/^[a-z][a-z0-9+.-]*:\/\//iu.test(trimmed)) {
    return trimmed;
  }

  try {
    return new URL(trimmed);
  } catch {
    return trimmed;
  }
}

function parseDataUrl(value: string): { mediaType?: string; data: string } | null {
  const match = value.trim().match(/^data:([^;,]+)?;base64,(.+)$/iu);
  if (!match?.[2]) {
    return null;
  }

  return {
    ...(match[1] ? { mediaType: match[1] } : {}),
    data: match[2]
  };
}

export function normalizeMessages(messages: GenerateModelInput["messages"]): ModelMessage[] | undefined {
  const normalized = (messages?.map((message) => ({
    role: message.role,
    content:
      typeof message.content === "string"
        ? message.content
        : message.content.map((part) => {
            if (part.type === "image") {
              const parsed = parseDataUrl(part.image);
              return {
                ...part,
                image: parsed?.data ?? maybeToUrl(part.image),
                mediaType: parsed?.mediaType ?? part.mediaType
              };
            }

            if (part.type === "file") {
              const parsed = parseDataUrl(part.data);
              return {
                ...part,
                data: parsed?.data ?? maybeToUrl(part.data),
                mediaType: parsed?.mediaType ?? part.mediaType
              };
            }

            return part;
          })
  })) ?? []) as ModelMessage[] | undefined;

  if (!normalized) {
    return undefined;
  }

  const parsed = modelMessageSchema.array().safeParse(normalized);
  if (!parsed.success) {
    throw new AppError(
      400,
      "invalid_model_messages",
      `Invalid AI SDK model messages: ${parsed.error.issues.map((issue) => issue.message).join("; ")}`
    );
  }

  return parsed.data;
}

export function toUsage(usage: Usage | undefined): Usage | undefined {
  if (!usage) {
    return undefined;
  }

  const inputTokens = usage.inputTokens ??
    (typeof (usage as Record<string, unknown>).promptTokens === "number" ? (usage as Record<string, unknown>).promptTokens as number : undefined);
  const outputTokens = usage.outputTokens ??
    (typeof (usage as Record<string, unknown>).completionTokens === "number" ? (usage as Record<string, unknown>).completionTokens as number : undefined);
  const totalTokens = usage.totalTokens ??
    ((inputTokens != null && outputTokens != null) ? inputTokens + outputTokens : undefined);

  if (inputTokens == null && outputTokens == null && totalTokens == null) {
    return undefined;
  }

  return {
    inputTokens,
    outputTokens,
    totalTokens,
  };
}

export function toPrompt(input: GenerateModelInput): { prompt: string } | { messages: ModelMessage[] } {
  if (input.prompt) {
    return { prompt: input.prompt };
  }

  const messages = normalizeMessages(input.messages);
  if (!messages || messages.length === 0) {
    throw new AppError(400, "invalid_model_input", "Either prompt or messages is required.");
  }

  return { messages };
}

function createSerialToolExecutor(): <T>(operation: () => Promise<T>) => Promise<T> {
  let queue = Promise.resolve();

  return async <T>(operation: () => Promise<T>) => {
    const next = queue.then(operation, operation);
    queue = next.then(
      () => undefined,
      () => undefined
    );
    return next;
  };
}

export function toAiTools(
  tools: EngineToolSet | undefined,
  signal: AbortSignal | undefined,
  parallelToolCalls: boolean | undefined
): ToolSet | undefined {
  if (!tools || Object.keys(tools).length === 0) {
    return undefined;
  }

  const runSerially = parallelToolCalls === false ? createSerialToolExecutor() : undefined;

  return Object.fromEntries(
    Object.entries(tools).map(([name, definition]) => [
      name,
      tool({
        description: definition.description,
        inputSchema: definition.inputSchema,
        execute: async (input, options) => {
          const executeTool = async () =>
            definition.execute(input, {
              abortSignal: signal,
              toolCallId: options.toolCallId
            });

          return runSerially ? runSerially(executeTool) : executeTool();
        },
        toModelOutput: ({ output }) => {
          if (
            isRecord(output) &&
            output.type === "content" &&
            Array.isArray(output.value)
          ) {
            const hasMedia = output.value.some(
              (item: Record<string, unknown>) =>
                item.type === "image-data" || item.type === "image-url"
            );
            if (hasMedia) {
              return {
                type: "content" as const,
                value: output.value.map((item: Record<string, unknown>) => {
                  if (item.type === "image-data") {
                    return {
                      type: "media" as const,
                      data: item.data,
                      mediaType: item.mediaType
                    };
                  }
                  if (item.type === "image-url") {
                    return {
                      type: "text" as const,
                      text: `[image url: ${item.url}]`
                    };
                  }
                  return item;
                })
              };
            }
          }
          return undefined;
        }
      })
    ])
  );
}

export function mergeToolSets(...toolSets: Array<ToolSet | undefined>): ToolSet | undefined {
  const mergedEntries = toolSets.flatMap((toolSet) => (toolSet ? Object.entries(toolSet) : []));
  if (mergedEntries.length === 0) {
    return undefined;
  }

  return Object.fromEntries(mergedEntries);
}

export function replaceLeadingSystemMessages(
  messages: ModelMessage[],
  systemMessages: Array<{ role: "system"; content: string }>
): ModelMessage[] {
  const firstNonSystemIndex = messages.findIndex((message) => message.role !== "system");
  const tail = firstNonSystemIndex === -1 ? [] : messages.slice(firstNonSystemIndex);
  return [...systemMessages.map((message) => ({ role: message.role, content: message.content })), ...tail] as ModelMessage[];
}

export function toStepResult(step: OnStepFinishEvent<ToolSet>): ModelStepResult {
  return {
    ...(typeof step.text === "string" ? { text: step.text } : {}),
    ...(Array.isArray(step.content) ? { content: step.content } : {}),
    ...(Array.isArray(step.reasoning) ? { reasoning: step.reasoning } : {}),
    ...(step.usage ? { usage: step.usage } : {}),
    ...(Array.isArray(step.warnings) ? { warnings: step.warnings } : {}),
    ...(step.request ? { request: step.request } : {}),
    ...(step.response ? { response: step.response } : {}),
    ...(step.providerMetadata ? { providerMetadata: step.providerMetadata } : {}),
    finishReason: step.finishReason,
    toolCalls: step.toolCalls.map((toolCall) => ({
      toolCallId: toolCall.toolCallId,
      toolName: toolCall.toolName,
      input: toolCall.input
    })),
    toolResults: step.toolResults.map((toolResult) => ({
      toolCallId: toolResult.toolCallId,
      toolName: toolResult.toolName,
      output: toolResult.output
    }))
  };
}

export function toToolCall(toolCall: { toolCallId: string; toolName: string; input: unknown }) {
  return {
    toolCallId: toolCall.toolCallId,
    toolName: toolCall.toolName,
    input: toolCall.input
  };
}

export function toToolResult(toolResult: { toolCallId: string; toolName: string; output: unknown }) {
  return {
    toolCallId: toolResult.toolCallId,
    toolName: toolResult.toolName,
    output: toolResult.output
  };
}

export function createImageExtractionModel(model: LanguageModel): LanguageModel {
  const middleware: LanguageModelMiddleware = {
    specificationVersion: "v3",
    transformParams: async ({ params }) => {
      const prompt = params.prompt;
      let changed = false;
      const newMessages: typeof prompt = [];

      for (const message of prompt) {
        if (message.role !== "tool") {
          newMessages.push(message);
          continue;
        }

        const toolParts = message.content;
        const imageParts: Array<{
          type: "file";
          data: string;
          mediaType: string;
        }> = [];
        const replacedParts: typeof toolParts = [];

        for (const part of toolParts) {
          if (part.type !== "tool-result") {
            replacedParts.push(part);
            continue;
          }

          const output = part.output;
          if (output.type !== "content" || !Array.isArray(output.value)) {
            replacedParts.push(part);
            continue;
          }

          const hasImage = output.value.some(
            (item) => item.type === "image-data" || item.type === "image-url"
          );

          if (!hasImage) {
            replacedParts.push(part);
            continue;
          }

          changed = true;
          const textItems = output.value.filter(
            (item) => item.type === "text"
          );
          const textContent = textItems.map((item) => item.text).join("\n");

          replacedParts.push({
            ...part,
            output: {
              type: "text" as const,
              value: textContent || "[Image displayed above]"
            }
          });

          for (const item of output.value) {
            if (item.type === "image-data") {
              imageParts.push({
                type: "file" as const,
                data: item.data,
                mediaType: item.mediaType
              });
            } else if (item.type === "image-url") {
              imageParts.push({
                type: "file" as const,
                data: item.url,
                mediaType: "image/png"
              });
            }
          }
        }

        if (replacedParts.length > 0) {
          newMessages.push({ ...message, content: replacedParts });
        }

        if (imageParts.length > 0) {
          newMessages.push({
            role: "user",
            content: [
              { type: "text" as const, text: "以下是工具返回的图片：" },
              ...imageParts
            ]
          });
        }
      }

      if (!changed) {
        return params;
      }

      return { ...params, prompt: newMessages };
    }
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return wrapLanguageModel({ model: model as any, middleware }) as LanguageModel;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function extractToolErrors(step: ModelStepResult): Array<{ toolCallId: string; toolName: string; error: unknown }> {
  const responseContent = isRecord(step.response) && Array.isArray(step.response.content) ? step.response.content : [];
  const stepContent = Array.isArray(step.content) ? step.content : [];
  const successfulToolCallIds = new Set(step.toolResults.map((toolResult) => toolResult.toolCallId));
  const toolErrors = new Map<string, { toolCallId: string; toolName: string; error: unknown }>();

  for (const part of [...stepContent, ...responseContent]) {
    if (
      !isRecord(part) ||
      part.type !== "tool-error" ||
      typeof part.toolCallId !== "string" ||
      typeof part.toolName !== "string" ||
      !("error" in part) ||
      successfulToolCallIds.has(part.toolCallId)
    ) {
      continue;
    }

    toolErrors.set(part.toolCallId, {
      toolCallId: part.toolCallId,
      toolName: part.toolName,
      error: part.error
    });
  }

  return [...toolErrors.values()];
}

export function toError(error: unknown): Error {
  if (error instanceof Error) {
    return error;
  }

  if (typeof error === "string") {
    return new Error(error);
  }

  return new Error("Unknown model stream error.");
}

export function toStepPreparation(
  preparation: ModelStepPreparation | undefined,
  messages: ModelMessage[],
  currentModel: LanguageModel,
  resolveModel: (modelName: string, modelDefinition?: GenerateModelInput["modelDefinition"]) => LanguageModel
): { model: LanguageModel; messages?: ModelMessage[]; activeTools?: string[] } | undefined {
  if (!preparation) {
    return undefined;
  }

  const preparedMessages = preparation.messages ? normalizeMessages(preparation.messages) : undefined;
  const nextMessages = preparation.systemMessages
    ? replaceLeadingSystemMessages(preparedMessages ?? messages, preparation.systemMessages)
    : preparedMessages;

  return {
    ...(preparation.model
      ? {
          model: resolveModel(preparation.model, preparation.modelDefinition)
        }
      : { model: currentModel }),
    ...(nextMessages ? { messages: nextMessages } : {}),
    ...(preparation.activeToolNames ? { activeTools: preparation.activeToolNames } : {})
  };
}

interface ContentPart {
  type: string;
  text?: string;
  data?: string;
  mediaType?: string;
  url?: string;
  [key: string]: unknown;
}

interface ToolResultPart {
  type: "tool-result";
  toolCallId: string;
  toolName: string;
  output: {
    type: string;
    value?: ContentPart[] | unknown;
    [key: string]: unknown;
  };
}

export function extractImageDataFromToolResults(messages: ModelMessage[]): ModelMessage[] | undefined {
  let changed = false;
  const result: ModelMessage[] = [];

  for (const message of messages) {
    if (message.role !== "tool" || typeof message.content === "string") {
      result.push(message);
      continue;
    }

    const needsExtraction = message.content.some(
      (part) =>
        part.type === "tool-result" &&
        part.output.type === "content" &&
        Array.isArray(part.output.value) &&
        part.output.value.some(
          (item: ContentPart) => item.type === "image-data" || item.type === "image-url"
        )
    );

    if (!needsExtraction) {
      result.push(message);
      continue;
    }

    changed = true;
    const toolParts: ToolResultPart[] = [];
    const userImageParts: Array<{ type: "image"; image: string; mediaType?: string } | { type: "text"; text: string }> = [];

    for (const part of message.content) {
      if (part.type !== "tool-result" || part.output.type !== "content" || !Array.isArray(part.output.value)) {
        toolParts.push(part as ToolResultPart);
        continue;
      }

      const imageParts = part.output.value.filter(
        (item: ContentPart) => item.type === "image-data" || item.type === "image-url"
      );
      const textParts = part.output.value.filter(
        (item: ContentPart) => item.type === "text"
      );

      if (imageParts.length === 0) {
        toolParts.push(part as ToolResultPart);
        continue;
      }

      const textContent = textParts.map((item: ContentPart) => item.text ?? "").join("\n");

      toolParts.push({
        ...part,
        output: {
          ...part.output,
          type: "text",
          value: textContent || "[Image displayed above]"
        }
      } as unknown as ToolResultPart);

      for (const img of imageParts) {
        if (img.type === "image-data" && img.data && img.mediaType) {
          userImageParts.push({
            type: "image" as const,
            image: img.data,
            mediaType: img.mediaType
          });
        } else if (img.type === "image-url" && img.url) {
          userImageParts.push({
            type: "image" as const,
            image: img.url
          });
        }
      }
    }

    if (toolParts.length > 0) {
      result.push({ role: "tool", content: toolParts } as ModelMessage);
    }

    if (userImageParts.length > 0) {
      result.push({
        role: "user",
        content: [
          { type: "text" as const, text: "以下是工具返回的图片：" },
          ...userImageParts
        ]
      } as ModelMessage);
    }
  }

  return changed ? result : undefined;
}
