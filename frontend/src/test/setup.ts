import "@testing-library/jest-dom/vitest";

Object.defineProperty(URL, "createObjectURL", {
  configurable: true,
  value: vi.fn(() => "blob:card-preview")
});

Object.defineProperty(URL, "revokeObjectURL", {
  configurable: true,
  value: vi.fn()
});
