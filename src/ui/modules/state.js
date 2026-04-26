// ui/modules/state.js

export const state = {
  selectedVersion: null,
  selectedVersionDisplay: null,
  versionsList: [],
  categoriesList: [],
  settingsState: { addons_view: 'list', worlds_view: 'list' },
  isShiftDown: false,
  versionsBulkState: {
    enabled: false,
    selected: new Set(),
  },
  modsBulkState: {
    enabled: false,
    selected: new Set(),
  },
  worldsBulkState: {
    enabled: false,
    selected: new Set(),
  },
  actionOverflowControllers: [],
  profilesState: {
    profiles: [{ id: 'default', name: 'Default' }],
    activeProfile: 'default',
  },
  versionsProfilesState: {
    profiles: [{ id: 'default', name: 'Default' }],
    activeProfile: 'default',
  },
  modsProfilesState: {
    profiles: [{ id: 'default', name: 'Default' }],
    activeProfile: 'default',
  },
  javaRuntimes: [],
  javaRuntimesLoaded: false,
  javaRuntimesLoading: false,
  javaRuntimesLoadAttempted: false,
  versionsPageDataLoaded: false,
  versionsPageDataLoading: false,
  versionsManifestError: false,
  versionsLoadRequestId: 0,
  modsPageDataLoaded: false,
  worldsPageDataLoaded: false,
  histolauncherUsername: '',
  localUsernameModified: false,
  activeInstallPollers: {},
  versionsAvailablePage: 1,
  selectedVersionCategories: [],
  settingsPreviewRequestId: 0,
  storageDirectoryValidationRequestId: 0,
};
