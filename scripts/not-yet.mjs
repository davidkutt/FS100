// Placeholder for root scripts whose implementation is scheduled for a later milestone.
// Fails on purpose so that nothing (e.g. CI) mistakes a placeholder for a real result.
const [script, milestone] = process.argv.slice(2);
console.error(
  `\`pnpm ${script}\` is not implemented yet — it is planned for ${milestone} (see plan.md §8).`,
);
process.exit(1);
