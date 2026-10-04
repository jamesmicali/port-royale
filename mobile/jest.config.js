/** @type {import('jest').Config} */
module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  roots: ["<rootDir>/engine"],
  testMatch: ["**/__tests__/**/*.test.ts"],
};
