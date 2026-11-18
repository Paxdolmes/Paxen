// App entry. First, catch JavaScript errors that would otherwise close the app (src/lib/errors.ts). Then the
// automatic-trips background task, which has to be defined before anything else runs, because iOS can start the
// app in the background just to report that Home or Work was left or reached (src/lib/autotrips.ts).
import './src/lib/errors'
import './src/lib/autotrips'
import 'expo-router/entry'
