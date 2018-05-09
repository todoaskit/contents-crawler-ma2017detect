import numpy as np
import time
from scipy.special import gammaln, psi
from corpus import BaseCorpus
from model import BaseModel

eps = 1e-100


class Corpus(BaseCorpus):

    def __init__(self, vocab, word_ids, word_cnt, n_topic):
        super().__init__(vocab, word_ids, word_cnt, n_topic)


class HDP(BaseModel):
    """
    The Hierarchical Dirichlet Process (HDP)
    Yee Whye Teh, Michael I. Jordan, Matthew J. Beal and David Blei, 2006
    Attributes
    ----------
    n_topic: int
        number of truncated topics for variational inference
    n_voca: int
        vocabulary size
    """

    def __init__(self, n_topic, n_voca, alpha=5., beta=5., dir_prior=0.5):
        super().__init__(n_topic, n_voca, alpha, beta, dir_prior)

    def fit(self, corpus, max_iter=100):
        """ Run variational EM to fit the model
        Parameters
        ----------
        max_iter: int
            maximum number of iterations
        corpus:
        Returns
        -------
        """

        for iteration in range(max_iter):
            lb = 0
            curr = time.clock()
            lb += self.update_C(corpus, False)
            lb += self.update_Z(corpus)
            lb += self.update_V(corpus)
            print('%d iter, %.2f time, %.2f lower_bound' % (iteration, time.clock() - curr, lb))

            if iteration > 3:
                self.lbs.append(lb)
            if iteration > 5:
                if (abs(self.lbs[-1] - self.lbs[-2]) / abs(self.lbs[-2])) < 1e-5:
                    break
                if self.lbs[-1] < self.lbs[-2]:
                    break

    # update per word v.d. phi
    def update_C(self, corpus, is_heldout):

        corpus.phi_doc = np.zeros([corpus.M, self.n_topic])
        psiGamma = psi(self.gamma)
        gammaSum = np.sum(self.gamma, 0)
        psiGammaSum = psi(np.sum(self.gamma, 0))
        lnZ = psi(corpus.A) - np.log(corpus.B)
        Z = corpus.A / corpus.B

        lb = 0
        if self.is_compute_lb:
            # expectation of p(eta) over variational q(eta)
            l1 = self.n_topic * gammaln(self.dir_prior * self.n_voca) \
                 - self.n_topic * self.n_voca * gammaln(self.dir_prior) \
                 - np.sum((self.dir_prior - 1) * (psiGamma - psiGammaSum))
            lb += l1
            # entropy of q(eta)
            l2 = np.sum(gammaln(gammaSum)) - np.sum(gammaln(self.gamma)) \
                 + np.sum((self.gamma - 1) * (psiGamma - psiGammaSum))
            lb -= l2

        if not is_heldout:
            # multinomial topic distribution prior
            self.gamma = np.zeros([self.n_voca, self.n_topic]) + self.dir_prior

        for m in range(corpus.M):
            ids = corpus.word_ids[m]
            cnt = corpus.word_cnt[m]

            # C = len(ids) x K
            E_ln_eta = psiGamma[ids, :] - psiGammaSum
            C = np.exp(E_ln_eta + lnZ[m, :])
            C = C / np.sum(C, 1)[:, np.newaxis]

            if not is_heldout:
                self.gamma[ids, :] += cnt[:, np.newaxis] * C
            corpus.phi_doc[m, :] = np.sum(cnt[:, np.newaxis] * C, 0)

            if self.is_compute_lb:
                # expectation of p(X) over variational q
                lb += np.sum(cnt[:, np.newaxis] * C * E_ln_eta)
                # expectation of p(C) over variational q
                l1 = np.sum(cnt[:, np.newaxis] * C * (lnZ[m, :] - np.log(np.sum(Z[m, :]))))
                lb += l1
                # entropy of q(C)
                l2 = np.sum(cnt[:, np.newaxis] * C * np.log(C + eps))
                lb -= l2

        # print ' E[p(eta,C,X)]-E[q(eta,C)] = %f' % lb
        return lb

    # update variational gamma prior a and b for Z_mk
    def update_Z(self, corpus):
        lb = 0
        bp = self.beta * self.p

        xi = np.sum(corpus.A / corpus.B, 1)  # m dim
        corpus.A = bp + corpus.phi_doc
        corpus.B = 1 + (corpus.Nm / xi)[:, np.newaxis]

        if self.is_compute_lb:
            # expectation of p(Z)
            E_ln_Z = psi(corpus.A) - np.log(corpus.B)
            l1 = np.sum((bp - 1) * E_ln_Z) - np.sum(corpus.A / corpus.B) - corpus.M * np.sum(gammaln(bp))
            lb += l1
            # entropy of q(Z)
            l2 = np.sum(corpus.A * np.log(corpus.B)) + np.sum((corpus.A - 1) * E_ln_Z) \
                 - np.sum(corpus.A) - np.sum(gammaln(corpus.A))
            lb -= l2
            # print ' E[p(Z)]-E[q(Z)] = %f' % lb

        return lb

    # coordinate ascent for V
    def update_V(self, corpus):
        lb = 0

        for i in range(self.c_a_max_step):
            one_V = 1 - self.V
            sumLnZ = np.sum(psi(corpus.A) - np.log(corpus.B), 0)  # K dim
            stickLeft = self.getStickLeft(self.V)  # prod(1-V_(dim-1))
            p = self.V * stickLeft

            psiV = psi(self.beta * p)

            vVec = self.beta * stickLeft * sumLnZ - corpus.M * self.beta * stickLeft * psiV

            for k in range(self.n_topic):
                tmp2 = self.beta * sum(sumLnZ[k + 1:] * p[k + 1:] / one_V[k])
                tmp3 = corpus.M * self.beta * sum(psiV[k + 1:] * p[k + 1:] / one_V[k])
                vVec[k] = vVec[k] - tmp2
                vVec[k] = vVec[k] + tmp3
                vVec[k] = vVec[k]
            vVec[:self.n_topic - 2] -= (self.alpha - 1) / one_V[:self.n_topic - 2]
            vVec[self.n_topic - 1] = 0
            step_stick = self.getstepSTICK(self.V, vVec, sumLnZ, self.beta, self.alpha, corpus.M)
            self.V = self.V + step_stick * vVec
            self.p = self.getP(self.V)

        if self.is_compute_lb:
            # expectation of p(V)
            lb += (self.n_topic - 1) * gammaln(self.alpha + 1) \
                  - (self.n_topic - 1) * gammaln(self.alpha) \
                  + np.sum((self.alpha - 1) * np.log(1 - self.V[:-1]))
            # print ' E[p(V)]-E[q(V)] = %f' % lb

        # print '%f diff     %f' % (new_ll - old_ll, lb)
        return lb

    # get stick length to update the gradient
    def getstepSTICK(self, curr, grad, sumlnZ, beta, alpha, M):
        _curr = curr[:len(curr) - 1]
        _grad = grad[:len(curr) - 1]
        _curr = _curr[_grad != 0]
        _grad = _grad[_grad != 0]

        step_zero = -_curr / _grad
        step_one = (1 - _curr) / _grad
        min_zero = 1
        min_one = 1
        if np.sum(step_zero > 0) > 0:
            min_zero = min(step_zero[step_zero > 0])
        if np.sum(step_one > 0) > 0:
            min_one = min(step_one[step_one > 0])
        max_step = min([min_zero, min_one])

        if max_step > 0:
            step_check_vec = np.array([0., .01, .125, .25, .375, .5, .625, .75, .875]) * max_step
        else:
            step_check_vec = list()

        f = np.zeros(len(step_check_vec))
        for ite in range(len(step_check_vec)):
            step_check = step_check_vec[ite]
            vec_check = curr + step_check * grad
            p = self.getP(vec_check)
            f[ite] = - M * np.sum(gammaln(beta * p)) \
                     + np.sum((beta * p - 1) * sumlnZ) + (alpha - 1.) * np.sum(np.log(1. - vec_check[:-1] + eps))

        if len(f) != 0:
            b = f.argsort()[-1]
            step = step_check_vec[b]
        else:
            step = 0

        if b == 1:
            rho = .5
            keep_cont = True
            fold = f[b]
            while keep_cont:
                step = rho * step
                vec_check = curr + step * grad
                tmp = np.zeros(vec_check.size)
                tmp[1:] = vec_check[:-1]
                p = vec_check * np.cumprod(1 - tmp)
                fnew = - M * np.sum(gammaln(beta * p)) \
                       + np.sum((beta * p - 1) * sumlnZ) + (alpha - 1.) * np.sum(np.log(1. - vec_check[:-1] + eps))
                if fnew > fold:
                    fold = fnew
                else:
                    keep_cont = False
            step = step / rho
        return step
