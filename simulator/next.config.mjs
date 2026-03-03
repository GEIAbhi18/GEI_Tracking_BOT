import fs from 'fs';
import path from 'path';

// Extract keys from the root GEI_Bot/.env file automatically
const parentEnvPath = path.resolve('../.env');
const envConfig = {};

if (fs.existsSync(parentEnvPath)) {
  const envContent = fs.readFileSync(parentEnvPath, 'utf8');
  envContent.split('\n').forEach(line => {
    // Basic .env parser (VAR="VALUE" or VAR=VALUE)
    const match = line.match(/^\s*([\w.-]+)\s*=\s*(.*)?\s*$/);
    if (match) {
      let key = match[1];
      let value = match[2] || '';
      value = value.replace(/^['"]|['"]$/g, ''); // strip quotes
      envConfig[key] = value;
      process.env[key] = value;
    }
  });
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  env: envConfig,
  images: {
    unoptimized: true
  }
};

export default nextConfig;
