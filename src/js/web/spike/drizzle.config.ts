import { defineConfig } from 'drizzle-kit'

export default defineConfig({
  dialect: 'sqlite',
  schema: './src/drizzle_schema.ts',
  out: './drizzle',
})
