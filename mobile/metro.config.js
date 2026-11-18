// Expo's default Metro setup, with one change: the release bundle keeps function names, so an error reported from
// a phone (src/lib/errors.ts) says which function it happened in. Costs a few kilobytes.
const { getDefaultConfig } = require('expo/metro-config')

const config = getDefaultConfig(__dirname)
const minifier = config.transformer.minifierConfig ?? {}
config.transformer.minifierConfig = {
  ...minifier,
  keep_fnames: true,
  mangle: { ...(minifier.mangle ?? {}), keep_fnames: true },
  compress: { ...(minifier.compress ?? {}), keep_fnames: true },
}

module.exports = config
