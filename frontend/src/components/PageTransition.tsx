import { motion, useReducedMotion } from 'framer-motion'

interface Props {
  children: React.ReactNode
}

/**
 * Route transition — framer-motion owns the fade/lift (it never fights GSAP,
 * which only runs inside pages). On top of it, a single filament "scan line"
 * sweeps top→bottom: the watchfloor re-acquiring the screen. Suppressed under
 * reduced motion.
 */
export default function PageTransition({ children }: Props) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
    >
      {!reduce && (
        <motion.div
          aria-hidden="true"
          className="pointer-events-none fixed inset-x-0 top-0 z-[60] h-px"
          style={{ background: 'linear-gradient(90deg, transparent, var(--filament-core), transparent)' }}
          initial={{ y: 0, opacity: 0.7 }}
          animate={{ y: '100vh', opacity: 0 }}
          transition={{ duration: 0.32, ease: 'easeOut' }}
        />
      )}
      {children}
    </motion.div>
  )
}
