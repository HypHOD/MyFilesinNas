export const openPage = (url: string) => {
    window.open(url);
}

type EllipsisPosition = "start" | "middle" | "end";

export const formatEllipsis = (
    value: string,
    maxLength: number,
    position: EllipsisPosition = "end"
) => {
    if (typeof value !== "string") {
        value = value == null ? "" : String(value);
    }

    const input = value;
    if (maxLength <= 0) {
        return "";
    }
    if (input.length <= maxLength) {
        return input;
    }

    if (maxLength === 1) {
        return "…";
    }

    const visibleCount = maxLength - 1;

    if (position === "start") {
        return `…${input.slice(-visibleCount)}`;
    }

    if (position === "middle") {
        const prefixLength = Math.ceil(visibleCount / 2);
        const suffixLength = Math.floor(visibleCount / 2);
        const suffix = suffixLength > 0 ? input.slice(-suffixLength) : "";
        return `${input.slice(0, prefixLength)}…${suffix}`;
    }

    return `${input.slice(0, visibleCount)}…`;
}
