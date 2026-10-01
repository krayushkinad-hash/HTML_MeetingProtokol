/**
 * Jest config for HMP frontend (vanilla JS, ES modules).
 *
 * Env: jsdom. Tests in tests dir. E2E for Playwright. Coverage for src/js.
 * ES modules from src are transformed via babel-jest.
 *
 * Uses .cjs extension because the project sets "type": "module" in package.json,
 * and Jest config files in that case must be CommonJS (Jest itself doesn't fully
 * support ESM config unless using --experimental-vm-modules with extra setup).
 *
 * rootDir is set to this file's directory so <rootDir> resolves to
 * hmp-frontend/ (where src/ and tests/ live), not its parent.
 */
module.exports = {
    testEnvironment: 'jsdom',
    rootDir: __dirname,
    roots: ['<rootDir>/tests'],
    testMatch: [
        '<rootDir>/tests/api/*.test.js',
        '<rootDir>/tests/views/*.test.js',
        '<rootDir>/tests/utils/*.test.js',
    ],
    setupFilesAfterEnv: ['<rootDir>/tests/setup.js'],

    transform: {
        '^.+\\.js$': ['babel-jest', { presets: [['@babel/preset-env', { targets: { node: 'current' } }]] }],
    },
    transformIgnorePatterns: [
        'node_modules/(?!(jest-)?@?testing-library/)',
    ],

    moduleNameMapper: {
        '^@api/(.*)$': '<rootDir>/src/js/api/$1',
        '^@views/(.*)$': '<rootDir>/src/js/views/$1',
        '^@components/(.*)$': '<rootDir>/src/js/views/components/$1',
        '^@utils/(.*)$': '<rootDir>/src/js/utils/$1',
        '^@storage/(.*)$': '<rootDir>/src/js/storage/$1',
        '^@tests/(.*)$': '<rootDir>/tests/$1',
    },

    collectCoverageFrom: [
        'src/js/api/client.js',
        'src/js/views/protocol.js',
        'src/js/views/settings.js',
        'src/js/utils/toast.js',
    ],
    coverageDirectory: '<rootDir>/coverage',
    coverageReporters: ['text', 'html', 'lcov', 'json-summary'],
    coverageThreshold: {
        global: {
            statements: 25,
            branches: 15,
            functions: 20,
            lines: 25,
        },
    },

    testTimeout: 15000,

    clearMocks: true,
    restoreMocks: true,
    resetModules: false,

    verbose: true,
};
